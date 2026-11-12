"""
Writes the day's post with Claude: the bilingual caption (EN first, PT-BR below)
and the copy and photo subject of each image, in one structured answer.

The caption is short on purpose. The lead fact lives on the image; the caption has
to earn the tap on "see more", which LinkedIn puts after roughly the first 140
characters on a phone.
"""
import json
import os
import re
from dataclasses import dataclass, field

import anthropic

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000

# Feed preview before "see more": about 140 characters on mobile.
MAX_HOOK_CHARS = 140
# Per language: the size the prompt asks for. Two of these plus hooks, labels
# and hashtags stay far below LinkedIn's 3000-character cap.
MAX_BODY_CHARS = 700
# The size at which a body is actually cut. Portuguese runs longer than English
# for the same facts, and cutting at 700 dropped the last paragraph from the PT
# version only, so the two languages no longer said the same thing.
TRIM_BODY_CHARS = 1000


@dataclass
class GeneratedContent:
    linkedin_pt: str
    linkedin_en: str
    main_url: str
    sources: list[str]
    image_teaser: str = ""
    image_subtitle: str = ""
    image_query: str = ""
    hashtags: str = ""
    images: list[dict] = field(default_factory=list)
    alt_text: str = ""


_OPENING_STYLES = """\
ÂNGULOS DE ABERTURA. Escolha o ÚNICO ângulo que o material da notícia principal sustenta
melhor (um rodízio fixo por dia produzia aberturas forçadas, como explicar "o mecanismo"
de uma notícia que era um número). Todos abrem por informação, nunca por reação emocional
ou suspense:
1. NÚMERO — Abra com o dado numérico que define a notícia e diga na mesma frase do que ele é medida. Ex: "O modelo resolve 71% do SWE-bench Verified, contra 49% da versão anterior."
2. O QUE MUDOU — Estado anterior numa frase, estado novo na seguinte. Sem adjetivo entre as duas.
3. MECANISMO — Abra explicando COMO a coisa funciona, não que ela existe. Ex: "O treinamento roda em duas etapas: primeiro X, depois Y."
4. CONSEQUÊNCIA DIRETA — Abra pelo efeito prático: o que passa a ser possível, mais barato ou inviável a partir de agora. Comece pelo efeito em si, nunca se dirigindo ao leitor ("se você trabalha com X...").
5. COMPARAÇÃO — Coloque o anúncio ao lado do concorrente ou da versão anterior e dê o dado que separa os dois.
6. LETRA MIÚDA — Abra pela condição, limite ou pré-requisito que o anúncio deixou em segundo plano. Só use se a notícia declarar essa condição; nunca deduza.
7. LINHA DO TEMPO — Ligue a notícia a um fato anterior datado que apareça no material fornecido.
8. DEFINIÇÃO — Explique em uma frase o termo técnico central antes de dar a notícia, para quem não acompanha a área.
"""

_LINKEDIN_SYSTEM = """\
Você escreve como Daniel Rios, estudante de tecnologia no Brasil que acompanha IA de perto.
Registro: analítico e informativo, primeira pessoa, sem formalidade corporativa e sem gíria.
O leitor sai do post sabendo o que aconteceu, quais são os números e por que aquilo importa
para quem trabalha com tecnologia. Você explica; não vende, não celebra e não se espanta em voz alta.

""" + _OPENING_STYLES + """
Fidelidade ao fato (regra mais importante):
- Todo número, data, nome, empresa, benchmark e valor tem que vir do material fornecido no prompt.
- Nunca invente, arredonde nem "melhore" um dado. Se falta um número, escreva a frase sem ele.
- Nunca atribua opinião a "especialistas", "o mercado", "analistas" ou "estudos". Cite o veículo pelo nome ou corte a afirmação.
- Você pode dar sua leitura pessoal, desde que fique claro que é sua e não venha disfarçada de fato.

Material desigual (acontece todo dia — não é motivo para não escrever):
- Cada notícia vem marcada. As que trazem TEXTO DO ARTIGO são as que você desenvolve:
  o número, o nome e o que mudou saem de lá.
- As marcadas SÓ TÍTULO entram apenas na linha de menções, em no máximo uma oração cada,
  dizendo o que o título afirma e atribuindo ao veículo ("o KRON4 noticiou que X").
  Nunca escreva um parágrafo sobre uma notícia da qual você só tem o título.
- Nunca descreva o que um produto faz, para que serve ou como se compara a outro se o
  material não disser. "Feito para respostas de baixa latência", "adiciona capacidades de
  segurança", "supera os concorrentes em velocidade" — se não está no texto, é invenção.
- Não acrescente contexto histórico que não está no material ("a versão anterior era o
  padrão para X", "isso vinha sendo esperado desde Y", "uma trajetória que começou há três
  anos"). Se você não leu, não escreva.
- Número de escala — quantos modelos a plataforma hospeda, quantos usuários tem, há quantos
  anos existe, qual a fatia de mercado — só entra se estiver escrito no material desta
  notícia. Você não sabe esses números de cabeça; o que parece memória é chute.
- Nome de veículo, empresa, pesquisador ou relatório só entra se aparecer no material.
  Nunca crie um nome de fonte para dar credibilidade a uma frase.
- Entradas do Hacker News trazem pontuação e número de comentários. São dados reais, mas
  NÃO são a notícia: nunca abra o post com eles, nunca compare duas notícias pela pontuação
  e nunca use "pontos no HN" como o número que define o parágrafo. No máximo uma menção no
  post inteiro, e só se ela disser algo que o resto não diz.
- Quando um título anuncia algo sem detalhar, diga isso: o que foi anunciado e o que ainda
  não se sabe. Uma lacuna declarada é informação; um número inventado não é.
- NUNCA responda pedindo mais material, comentando a qualidade das fontes ou explicando por
  que não dá para escrever. A resposta é sempre o post nos blocos pedidos, sem exceção.

Proibido (padrões que fazem o texto soar como IA ou como propaganda):
- Importância inflada: "muda o jogo", "divisor de águas", "marco histórico", "revolucionário", "nunca mais será o mesmo", "game changer", "watershed moment", "seismic shift".
- Linguagem de venda: "poderoso", "robusto", "solução completa", "impressionante", "groundbreaking", "powerful", "seamless", "must-watch".
- Abertura de falsa franqueza: "Olha", "Honestamente", "Vou ser sincero", "A real é que", "Look", "Here's the thing", "Let's be honest".
- Anunciar o próximo ponto: "vamos ao que interessa", "o que você precisa saber", "let's dive in", "here's the breakdown".
- Fecho otimista genérico: "o futuro promete", "estamos só começando", "exciting times ahead". Termine no último fato concreto.
- Sequência de frases-fragmento dramáticas ("Sem aviso. Sem debate. Só o anúncio."). Uma frase curta para ênfase, no máximo.
- Frase de efeito vazia: "X é a nova moeda de Y", "não é uma ferramenta, é um espelho".
- Fecho-fórmula que nomeia uma tensão em vez de dar um fato: "é onde mora a tensão real", "é aí que está a verdadeira questão", "is where the real tension lives", "that's the real question here". Se o contraste entre duas notícias importa, diga qual é o dado dos dois lados.
- Dirigir-se ao leitor para justificar a notícia: "se você trabalha com X, precisa saber que", "if you're hiring right now, you need to know". Dê o fato; a relevância aparece sozinha.
- Clichês de abertura: "Hoje em dia", "Na era da IA", "Com o avanço da", "No cenário atual", "É indiscutível".
- Emoji. Nenhum, em nenhuma das duas versões.
- Bullet com hífen (-). Use parágrafos corridos.
- Negrito para dar ênfase a frases inteiras.

Forma:
- Verbo simples: "é", "tem", "faz". Evite "se apresenta como", "se consolida como", "representa um".
- Prefira o número, o nome próprio e a data ao adjetivo.
- Varie o comprimento das frases. Parágrafos de 1 a 3 linhas, com linha em branco entre eles.
- Travessão (—) é permitido.
- A versão PT é português brasileiro correto: concordância de gênero e número, artigo antes
  de nome de empresa quando o uso pede ("a Amazon", "a Mistral"), regência certa. Nome de
  produto e termo técnico ficam em inglês; o resto da frase, não.
- Respeite os limites de tamanho de cada campo dados no prompt. Se passar, corte a frase que carrega menos informação, não as frases com número.
- A legenda termina com uma pergunta específica sobre uma decisão real que o leitor da área enfrenta, ou com o último fato concreto. Nunca "o que vocês acham?".
- Nenhum campo de texto leva hashtag. As hashtags saem no campo próprio.
"""

_USER_TMPL = """\
Escreva o post do LinkedIn sobre as principais notícias de IA e tecnologia de ontem ({date}).
O post tem duas partes: de 1 a 4 imagens com texto EM INGLÊS e uma legenda curta em inglês e
em português. As notícias são:

{stories}

Contexto das últimas 2 semanas (NÃO repita esses tópicos principais):
{recent_context}

ESCOLHA DA NOTÍCIA
A notícia nº 1 da lista é a mais relevante do dia pelo ranking (cobertura em vários veículos,
dinheiro envolvido, processo, regulação, lançamento grande ou polêmica em curso). O post é
sobre ela. Só desça na lista se a nº 1 estiver marcada como SÓ TÍTULO: aí use a primeira que
tenha material. A lista pode trazer o MESMO acontecimento em duas entradas, de veículos
diferentes: trate as duas como uma notícia só.

IMAGENS (inglês nativo, não inglês traduzido)
Cada imagem é uma FOTO REAL do assunto da notícia, com um título e um fato por cima. A foto é
buscada na Wikimedia Commons pelo nome que você der, então o assunto tem que ser algo que
existe e tem foto: a pessoa citada, a sede ou o prédio da empresa, o produto físico, o chip, o
data center, o tribunal, a cidade.
- A imagem 1 é a notícia principal, com a pessoa ou a coisa mais reconhecível dela.
- Prefira ROSTO a prédio: uma pessoa conhecida para o feed mais do que uma fachada. Se a
  notícia tem uma pessoa central, é ela. Se a notícia é sobre uma empresa, vale o CEO ou o
  fundador dessa empresa, como os veículos fazem. Produto físico (chip, robô, aparelho) vem em
  seguida. Sede ou prédio fica como último termo de busca, para quando não houver foto dos
  outros. Se o post tiver mais de uma imagem, não use o mesmo tipo de cena em todas.
- Só acrescente outra imagem quando houver OUTRO assunto real e diferente para mostrar: uma
  segunda pessoa ou empresa da notícia principal, ou outra notícia do dia que tenha material.
  Uma imagem boa vale mais que quatro; não crie imagem para completar número. Máximo 4.
- Em cada imagem:
  · subjects: de 2 a 3 termos de busca, na ordem de preferência, cada um o nome de algo real
    ("Jensen Huang", depois "Nvidia GPU", depois "Nvidia headquarters"). Pessoa pelo nome
    completo. Nunca um conceito ("artificial intelligence", "stock market", "governance").
  · kicker: rótulo de 1 a 3 palavras (a empresa ou o tema).
  · headline: o fato em até 9 palavras, com sujeito e verbo. Sem ponto final.
  · fact: uma frase de até 16 palavras com o número ou o detalhe que a headline não deu.
  · source: o veículo de onde saiu o fato, pelo nome.
- Duas imagens não repetem o mesmo assunto nem o mesmo fato.
- Uma acusação contra uma pessoa só entra atribuída ao veículo ("reportedly", "according to")
  e nunca ponha a foto de alguém que a notícia só cita de passagem ou que não é figura
  pública.

LEGENDA
- hook_en / hook_pt: a primeira linha do post, no máximo {max_hook} caracteres. É tudo o que
  aparece antes do "ver mais". Um fato com número ou nome próprio, escrito como frase
  completa. Sem pergunta retórica, sem dois-pontos de suspense, sem "aqui está o porquê".
- body_en / body_pt: de 2 a 3 parágrafos curtos, no máximo {max_body} caracteres por idioma.
  Não repete o hook. O corpo dá a leitura que as imagens não dão: o que o fato muda, o que
  ainda não se sabe, ou como ele se liga a outra notícia do material. A última frase é uma
  pergunta específica sobre uma decisão real de quem trabalha na área, ou o último fato.
- A versão em português traz os mesmos fatos e os mesmos números da versão em inglês, na
  mesma ordem de parágrafos, escrita como quem pensa em português (não é tradução literal).
  Nome de produto, empresa, benchmark e termo técnico consagrado ficam em inglês; o resto da
  frase, não: "desempenho" e não "performance", "queda" e não "outage". Artigo antes de nome
  de empresa ("a Nvidia", "a Anthropic"). Valor em dólar: "US$ 13 bilhões". Decimal com
  vírgula: "62,7%".
- hashtags: de 3 a 5, sem o #, sem espaço, específicas ao tema do dia (ex. "OpenSourceLLM").

IMAGEM RESERVA
- image_query: de 2 a 4 palavras EM INGLÊS com uma cena concreta e fotografável ligada ao
  tema, usada só se nenhuma foto real da imagem 1 for encontrada. Sem nome de marca.
- alt_text: uma frase em inglês descrevendo as imagens para leitor de tela.

Todo número que você escrever, em qualquer campo, é copiado do material como está lá. Um
programa confere cada número contra o material depois da sua resposta e descarta a imagem que
trouxer um número que não está lá, inclusive número arredondado.
"""

_IMAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "subjects": {"type": "array", "items": {"type": "string"}},
        "kicker": {"type": "string"},
        "headline": {"type": "string"},
        "fact": {"type": "string"},
        "source": {"type": "string"},
    },
    "required": ["subjects", "kicker", "headline", "fact", "source"],
    "additionalProperties": False,
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["stat", "bars", "points"]},
        "kicker": {"type": "string"},
        "title": {"type": "string"},
        "value": {"type": "string"},
        "label": {"type": "string"},
        "body": {"type": "string"},
        "bars": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "number"},
                    "display": {"type": "string"},
                    "highlight": {"type": "boolean"},
                },
                "required": ["label", "value", "display", "highlight"],
                "additionalProperties": False,
            },
        },
        "points": {"type": "array", "items": {"type": "string"}},
        "source": {"type": "string"},
    },
    "required": ["type", "kicker", "title", "value", "label", "body", "bars", "points", "source"],
    "additionalProperties": False,
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "images": {"type": "array", "items": _IMAGE_SCHEMA},
        "hook_en": {"type": "string"},
        "body_en": {"type": "string"},
        "hook_pt": {"type": "string"},
        "body_pt": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "image_query": {"type": "string"},
        "alt_text": {"type": "string"},
    },
    "required": [
        "images", "hook_en", "body_en",
        "hook_pt", "body_pt", "hashtags", "image_query", "alt_text",
    ],
    "additionalProperties": False,
}


def _call_claude(system: str, user: str) -> dict:
    """One structured answer. The schema replaces the old ---EN--- separators
    and the assistant prefill, which current models reject with a 400."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    ) as stream:
        msg = stream.get_final_message()

    usage = msg.usage
    print(
        f"[content] {MODEL}: stop_reason={msg.stop_reason!r}, "
        f"{usage.input_tokens} tokens in, {usage.output_tokens} out"
    )
    if msg.stop_reason != "end_turn":
        raise RuntimeError(
            f"Claude stopped with {msg.stop_reason!r} — refusing to post a "
            "half-generated digest. The next cron attempt retries today."
        )
    text = next((b.text for b in msg.content if b.type == "text"), "")
    return json.loads(text)


# ── Number check ─────────────────────────────────────────────────────────────
_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(text: str) -> set[str]:
    """Numbers in a text, normalised so "62,7" and "62.7" or "1,404" and
    "1.404" compare equal. Single digits are skipped: "2 companies" is counting,
    not a figure anyone could look up."""
    found = set()
    for raw in _NUM.findall(text or ""):
        norm = raw.replace(",", ".").strip(".")
        if len(norm.replace(".", "")) >= 2:
            found.add(norm)
    return found


def _material_numbers(stories: list[dict]) -> set[str]:
    parts = []
    for s in stories:
        parts += [s.get("title", ""), s.get("summary", ""), s.get("article", "")]
    return _numbers(" ".join(parts))


def _check_images(raw: dict, stories: list[dict]) -> list[dict]:
    """Drop every image carrying a number the source material does not have.

    The model is told to copy figures as written. This is the part that does
    not take its word for it: the image puts one fact in large type, and a
    wrong number there is the whole post. The lead image is never dropped,
    because the post needs it; it loses the offending line instead.
    """
    known = _material_numbers(stories)
    images = []
    for n, image in enumerate((raw.get("images") or [])[:4]):
        image = dict(image, headline=image.get("headline", "").strip().rstrip("."))
        if not image["headline"] or not image.get("subjects"):
            print("[content] Dropped an image with no headline or no subject")
            continue
        bad_head = _numbers(image["headline"]) - known
        bad_fact = _numbers(image.get("fact", "")) - known
        if bad_fact:
            print(f"[content] Removed a fact with numbers not in the material: {sorted(bad_fact)}")
            image["fact"] = ""
        if bad_head:
            print(f"[content] Headline with numbers not in the material: {sorted(bad_head)}")
            if n > 0:
                continue
            image["headline"] = stories[0]["title"][:80]
        images.append(image)

    for name in ("hook_en", "body_en", "hook_pt", "body_pt"):
        unknown = _numbers(raw.get(name, "")) - known
        if unknown:
            # Prose cannot be repaired by deleting a field, so this one is a
            # loud line in the run log instead of a silent pass.
            print(f"[WARN] {name} carries numbers not found in the material: {sorted(unknown)}")
    return images


def _trim_hook(hook: str) -> str:
    hook = " ".join((hook or "").split())
    if len(hook) <= MAX_HOOK_CHARS:
        return hook
    return hook[:MAX_HOOK_CHARS].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"


def _trim_to_paragraph(text: str, limit: int) -> str:
    """Cut to whole sentences under the limit.

    LinkedIn caps a post at 3000 characters, and both versions plus the divider
    and the hashtags share that budget. Dropping the overflowing paragraph whole
    is too blunt: a PT version 51 characters over the limit lost its closing
    paragraph and came out at 625 against the English version's 1209, so the
    Portuguese reader never saw the other stories at all.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text

    kept: list[str] = []
    used = 0
    for para in text.split("\n\n"):
        gap = 2 if kept else 0
        if used + gap + len(para) <= limit:
            kept.append(para)
            used += gap + len(para)
            continue

        # Keep the sentences of this paragraph that still fit.
        budget = limit - used - gap
        sentences = re.split(r"(?<=[.!?])\s+", para)
        partial: list[str] = []
        for sentence in sentences:
            candidate = " ".join(partial + [sentence])
            if len(candidate) > budget:
                break
            partial.append(sentence)
        # A one-line remnant ("O timing importa.") reads worse than no
        # paragraph at all.
        remnant = " ".join(partial)
        if len(remnant) >= 80:
            kept.append(remnant)
        break

    if not kept:
        return text[:limit].rsplit(" ", 1)[0].rstrip(",;—-")
    return "\n\n".join(kept)


def _same_text(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"\s+", " ", s or "").strip().lower()
    return bool(norm(a)) and norm(a) == norm(b)


def _format_stories_for_prompt(stories: list[dict]) -> str:
    lines = []
    for i, s in enumerate(stories, 1):
        summary = (s.get("summary") or "").strip()[:200]
        article = (s.get("article") or "").strip()
        block = [
            f"{i}. [{s.get('outlet') or s['source']}] {s['title']}",
            f"   URL: {s.get('url', 'N/A')}",
            f"   Resumo: {summary or 'sem resumo'}",
        ]
        also = s.get("also_covered_by") or []
        if also:
            block.append(f"   Também noticiado por: {', '.join(also)}")
        if article:
            block.append(f"   TEXTO DO ARTIGO: {article}")
            block.append("   -> Tem material. Pode desenvolver em profundidade.")
        elif len(summary) >= 150:
            block.append("   -> Resumo do veículo serve de material. Pode desenvolver, atribuindo ao veículo.")
        else:
            block.append("   -> SÓ TÍTULO. Vai para a linha de menções, não para um parágrafo.")
        lines.append("\n".join(block))
    return "\n\n".join(lines)


def _format_recent_context(history: dict) -> str:
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    topics = []
    for post in history.get("posts", []):
        try:
            dt = datetime.fromisoformat(post["date"]).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if dt >= cutoff:
            topics.extend(post.get("topics", []))
    if not topics:
        return "Nenhum contexto disponível ainda."
    return "- " + "\n- ".join(topics[:20])


def _join_caption(hook: str, body: str) -> str:
    body = _trim_to_paragraph(body, TRIM_BODY_CHARS)
    return f"{_trim_hook(hook)}\n\n{body}".strip() if body else _trim_hook(hook)


def generate_content(
    stories: list[dict],
    history: dict,
    date_str: str,
    dry_run: bool = False,
) -> GeneratedContent:
    if not stories:
        raise ValueError("No stories to generate content from")

    main_story = stories[0]
    prompt = _USER_TMPL.format(
        date=date_str,
        stories=_format_stories_for_prompt(stories),
        recent_context=_format_recent_context(history),
        max_hook=MAX_HOOK_CHARS,
        max_body=MAX_BODY_CHARS,
    )

    print("[content] Generating caption and image copy...")
    # A dry run still generates real text: the copy is the thing worth
    # previewing. Only posting and history are skipped.
    if dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        print("[content] No ANTHROPIC_API_KEY — using placeholder copy")
        raw = {
            "images": [{"subjects": ["Nvidia headquarters"], "kicker": "Dry run",
                        "headline": main_story.get("title", "")[:60], "fact": "",
                        "source": main_story.get("source", "")}],
            "hook_en": "[DRY RUN] EN hook", "body_en": "EN body placeholder.",
            "hook_pt": "[DRY RUN] gancho PT", "body_pt": "Corpo PT de exemplo.",
            "hashtags": ["AI", "Tech"], "image_query": "data center servers", "alt_text": "Placeholder",
        }
    else:
        raw = _call_claude(_LINKEDIN_SYSTEM, prompt)

    if not raw.get("hook_en") or not raw.get("body_en"):
        raise ValueError("Claude answer carried no English caption")

    images = _check_images(raw, stories)
    lead = images[0] if images else {}
    linkedin_en = _join_caption(raw["hook_en"], raw["body_en"])
    linkedin_pt = _join_caption(raw.get("hook_pt", ""), raw.get("body_pt", ""))

    # One language repeated twice reads as a bug to anyone scrolling the feed.
    if _same_text(linkedin_en, linkedin_pt):
        print("[content] EN and PT captions are identical — publishing one version only")
        linkedin_pt = ""

    tags = []
    for tag in raw.get("hashtags") or []:
        tag = re.sub(r"[^0-9A-Za-zÀ-ÿ_]", "", tag)
        if tag and tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag)

    result = GeneratedContent(
        linkedin_pt=linkedin_pt,
        linkedin_en=linkedin_en,
        main_url=main_story.get("url", ""),
        sources=list({s.get("outlet") or s["source"] for s in stories}),
        # The single-image fallback card still takes a teaser and a subtitle.
        image_teaser=lead.get("headline") or main_story.get("title", "")[:60],
        image_subtitle=lead.get("fact", ""),
        image_query=(raw.get("image_query") or "").strip() or "artificial intelligence technology",
        hashtags=" ".join(f"#{t}" for t in tags[:5]),
        images=images,
        alt_text=(raw.get("alt_text") or "").strip(),
    )

    print(
        f"[content] Caption EN {len(result.linkedin_en)} chars, PT {len(result.linkedin_pt)} chars; "
        f"{len(images)} image(s) planned"
    )
    return result


if __name__ == "__main__":
    import sys
    from datetime import date
    from news_fetcher import fetch_news, load_history

    stories = fetch_news(dry_run=True)
    content = generate_content(stories, load_history(), str(date.today()), dry_run="--dry-run" in sys.argv)
    print(json.dumps(content.images, indent=2, ensure_ascii=False))
    print(content.linkedin_en, "\n\n", content.linkedin_pt, "\n\n", content.hashtags)

"""
Writes the day's post with Claude: the bilingual caption (EN first, PT-BR below)
and the content of the carousel slides, in one structured answer.

The caption is short on purpose. The facts live on the slides; the caption has
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
# Per language. Two of these plus hooks, labels and hashtags stay far below
# LinkedIn's 3000-character cap.
MAX_BODY_CHARS = 700


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
    deck: dict = field(default_factory=dict)
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
O post tem duas partes: um carrossel de slides EM INGLÊS e uma legenda curta em inglês e em
português. As notícias são:

{stories}

Contexto das últimas 2 semanas (NÃO repita esses tópicos principais):
{recent_context}

ESCOLHA DA NOTÍCIA
A notícia nº 1 da lista é a mais relevante do dia pelo ranking (cobertura em vários veículos,
dinheiro envolvido, processo, regulação, lançamento grande ou polêmica em curso). O post é
sobre ela. Só desça na lista se a nº 1 estiver marcada como SÓ TÍTULO: aí use a primeira que
tenha material. A lista pode trazer o MESMO acontecimento em duas entradas, de veículos
diferentes: trate as duas como uma notícia só.

CARROSSEL (inglês nativo, não inglês traduzido)
Quem passa os slides lê pouco texto por tela, em letra grande. Cada slide carrega UM fato.
- headline: a notícia principal em até 9 palavras, com o sujeito e o fato. Sem ponto final.
- dek: uma frase de até 18 palavras com o segundo fato mais importante. Não repete a headline.
- slides: de 2 a 4 slides sobre a notícia principal, cada um de um tipo:
  · "stat": um número em destaque. value é o número como aparece no material, compacto
    ("$84.6B", "71%", "825M"), com no máximo 8 caracteres; label diz do que ele é medida, em
    até 8 palavras; body explica em até 30 palavras.
  · "bars": comparação entre 2 a 4 números DA MESMA UNIDADE que estejam no material (antes e
    depois, empresa A e B, faixa mínima e máxima). Em cada barra: label (até 5 palavras),
    value (o número puro, na mesma unidade em todas as barras), display (como se escreve,
    "$965B") e highlight (true só na barra que é a notícia). title em até 6 palavras; body é
    uma frase de até 20 palavras com o que a comparação mostra. Só use "bars" se os números
    existirem no material; nunca estime um valor para completar o gráfico.
  · "points": de 2 a 3 frases de até 18 palavras cada, cada uma com um fato. title em até 6
    palavras.
  Em todo slide: kicker (rótulo de 1 a 3 palavras, ex. "The numbers") e source (o veículo de
  onde saiu o fato, pelo nome). Preencha só os campos do tipo escolhido; os outros ficam
  vazios ("" ou []).
- roundup: de 0 a 3 outras notícias do dia, uma frase de até 20 palavras cada, com o veículo
  em source. Notícia SÓ TÍTULO entra aqui dizendo só o que o título afirma.
- Não repita o mesmo número em dois slides, salvo o da headline.

LEGENDA
- hook_en / hook_pt: a primeira linha do post, no máximo {max_hook} caracteres. É tudo o que
  aparece antes do "ver mais". Um fato com número ou nome próprio, escrito como frase
  completa. Sem pergunta retórica, sem dois-pontos de suspense, sem "aqui está o porquê".
- body_en / body_pt: de 2 a 3 parágrafos curtos, no máximo {max_body} caracteres por idioma.
  Não repete o hook. O corpo dá a leitura que os slides não dão: o que o fato muda, o que
  ainda não se sabe, ou como ele se liga a outra notícia do material. A última frase é uma
  pergunta específica sobre uma decisão real de quem trabalha na área, ou o último fato.
- A versão em português traz os mesmos fatos e os mesmos números da versão em inglês, na
  mesma ordem de parágrafos, escrita como quem pensa em português (não é tradução literal).
  Nome de produto, empresa, benchmark e termo técnico consagrado ficam em inglês; o resto da
  frase, não: "desempenho" e não "performance", "queda" e não "outage". Artigo antes de nome
  de empresa ("a Nvidia", "a Anthropic"). Valor em dólar: "US$ 13 bilhões". Decimal com
  vírgula: "62,7%".
- hashtags: de 3 a 5, sem o #, sem espaço, específicas ao tema do dia (ex. "OpenSourceLLM").

IMAGEM
- image_query: de 2 a 4 palavras EM INGLÊS com uma cena concreta e fotografável ligada ao
  tema, para buscar a foto da capa em banco de imagens. Sem nome de marca. Ex.: "data center
  servers", "trading floor screens", "courtroom interior".
- alt_text: uma frase em inglês descrevendo o carrossel para leitor de tela.

Todo número que você escrever, em qualquer campo, é copiado do material como está lá. Um
programa confere cada número contra o material depois da sua resposta e descarta o slide que
trouxer um número que não está lá, inclusive número arredondado.
"""

_SLIDE_SCHEMA = {
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
        "headline": {"type": "string"},
        "dek": {"type": "string"},
        "slides": {"type": "array", "items": _SLIDE_SCHEMA},
        "roundup": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "source": {"type": "string"}},
                "required": ["text", "source"],
                "additionalProperties": False,
            },
        },
        "hook_en": {"type": "string"},
        "body_en": {"type": "string"},
        "hook_pt": {"type": "string"},
        "body_pt": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "image_query": {"type": "string"},
        "alt_text": {"type": "string"},
    },
    "required": [
        "headline", "dek", "slides", "roundup", "hook_en", "body_en",
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


def _slide_text(slide: dict) -> str:
    bars = " ".join(f"{b.get('label', '')} {b.get('display', '')}" for b in slide.get("bars") or [])
    return " ".join(
        [slide.get("title", ""), slide.get("value", ""), slide.get("label", ""),
         slide.get("body", ""), bars, " ".join(slide.get("points") or [])]
    )


def _valid_slide(slide: dict) -> bool:
    kind = slide.get("type")
    if kind == "stat":
        return bool(slide.get("value") and slide.get("label"))
    if kind == "bars":
        bars = slide.get("bars") or []
        return 2 <= len(bars) <= 4 and all(b.get("value", 0) > 0 for b in bars) and bool(slide.get("title"))
    if kind == "points":
        return 2 <= len(slide.get("points") or []) <= 3 and bool(slide.get("title"))
    return False


def _check_deck(raw: dict, stories: list[dict]) -> dict:
    """Drop every slide carrying a number the source material does not have.

    The model is told to copy figures as written. This is the part that does
    not take its word for it: a slide puts one number in 250px type, and a
    wrong one there is the whole post.
    """
    known = _material_numbers(stories)
    slides = []
    for slide in raw.get("slides") or []:
        if not _valid_slide(slide):
            print(f"[content] Dropped a malformed {slide.get('type')!r} slide")
            continue
        unknown = _numbers(_slide_text(slide)) - known
        if unknown:
            print(f"[content] Dropped slide {slide.get('kicker')!r}: numbers not in the material: {sorted(unknown)}")
            continue
        slides.append(slide)

    roundup = []
    for item in (raw.get("roundup") or [])[:3]:
        unknown = _numbers(item.get("text", "")) - known
        if unknown or not item.get("text"):
            print(f"[content] Dropped a roundup line: numbers not in the material: {sorted(unknown)}")
            continue
        roundup.append(item)

    for name in ("headline", "dek", "hook_en", "body_en", "hook_pt", "body_pt"):
        unknown = _numbers(raw.get(name, "")) - known
        if unknown:
            # Prose cannot be repaired by deleting a field, so this one is a
            # loud line in the run log instead of a silent pass.
            print(f"[WARN] {name} carries numbers not found in the material: {sorted(unknown)}")

    return {
        "headline": raw.get("headline", "").strip().rstrip("."),
        "dek": raw.get("dek", "").strip(),
        "slides": slides[:4],
        "roundup": roundup,
    }


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
    body = _trim_to_paragraph(body, MAX_BODY_CHARS)
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

    print("[content] Generating caption and slides...")
    # A dry run still generates real text: the copy is the thing worth
    # previewing. Only posting and history are skipped.
    if dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        print("[content] No ANTHROPIC_API_KEY — using placeholder copy")
        raw = {
            "headline": main_story.get("title", "")[:70], "dek": "Placeholder deck for a dry run without an API key.",
            "slides": [{"type": "points", "kicker": "Dry run", "title": "Placeholder slide", "value": "",
                        "label": "", "body": "", "bars": [], "source": main_story.get("source", ""),
                        "points": ["First placeholder point.", "Second placeholder point."]}],
            "roundup": [], "hook_en": "[DRY RUN] EN hook", "body_en": "EN body placeholder.",
            "hook_pt": "[DRY RUN] gancho PT", "body_pt": "Corpo PT de exemplo.",
            "hashtags": ["AI", "Tech"], "image_query": "data center servers", "alt_text": "Placeholder",
        }
    else:
        raw = _call_claude(_LINKEDIN_SYSTEM, prompt)

    if not raw.get("hook_en") or not raw.get("body_en"):
        raise ValueError("Claude answer carried no English caption")

    deck = _check_deck(raw, stories)
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
        image_teaser=deck["headline"] or main_story.get("title", "")[:60],
        image_subtitle=deck["dek"],
        image_query=(raw.get("image_query") or "").strip() or "artificial intelligence technology",
        hashtags=" ".join(f"#{t}" for t in tags[:5]),
        deck=deck,
        alt_text=(raw.get("alt_text") or "").strip(),
    )

    print(
        f"[content] Caption EN {len(result.linkedin_en)} chars, PT {len(result.linkedin_pt)} chars; "
        f"{len(deck['slides'])} content slides, {len(deck['roundup'])} roundup lines"
    )
    return result


if __name__ == "__main__":
    import sys
    from datetime import date
    from news_fetcher import fetch_news, load_history

    stories = fetch_news(dry_run=True)
    content = generate_content(stories, load_history(), str(date.today()), dry_run="--dry-run" in sys.argv)
    print(json.dumps(content.deck, indent=2, ensure_ascii=False))
    print(content.linkedin_en, "\n\n", content.linkedin_pt, "\n\n", content.hashtags)

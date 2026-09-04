"""
Generates bilingual (EN + PT-BR) LinkedIn posts using Claude Haiku.
Opening angle rotates deterministically by day-of-year (8 angles, cycles every 8 days).
"""
import os
import re
from dataclasses import dataclass
from datetime import date as date_type

import anthropic

MODEL = "claude-haiku-4-5-20251001"
# EN post plus tags, teaser, subtitle and image query in the first call; the
# Portuguese version alone in the second. The old single call at 1200 was cut
# inside the PT block on 2026-09-01, which killed every block after it.
MAX_TOKENS_EN = 2200
MAX_TOKENS_PT = 1500
MAX_TOKENS_RETRY = 3500
# LinkedIn cuts a post at 3000 characters. The labels, the divider and the
# hashtags cost about 160, leaving ~1420 per version. 1250 was over-cautious
# and cost a Portuguese version its closing paragraph over a 39-char overflow.
MAX_VERSION_CHARS = 1400


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


_OPENING_STYLES = """\
ÂNGULOS DE ABERTURA (use EXATAMENTE o ângulo do número indicado no prompt).
Todos abrem por informação, nunca por reação emocional ou suspense:
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
- Bullet com hífen (-). Use → ou parágrafos corridos.
- Negrito para dar ênfase a frases inteiras.

Forma:
- Verbo simples: "é", "tem", "faz". Evite "se apresenta como", "se consolida como", "representa um".
- Prefira o número, o nome próprio e a data ao adjetivo.
- Varie o comprimento das frases. Parágrafos de 1 a 3 linhas, com linha em branco entre eles.
- Travessão (—) é permitido.
- A versão PT é português brasileiro correto: concordância de gênero e número, artigo antes
  de nome de empresa quando o uso pede ("a Amazon", "a Mistral"), regência certa. Nome de
  produto e termo técnico ficam em inglês; o resto da frase, não.
- Máximo 1400 caracteres por versão. Antes de responder, confira o tamanho; se passar, corte o parágrafo que carrega menos informação, não as frases com número.
- Termine com uma pergunta específica sobre uma decisão real que o leitor da área enfrenta, ou com o último fato concreto. Nunca "o que vocês acham?".
- O corpo do post não leva hashtag. As hashtags saem em bloco separado.
"""

_EN_USER_TMPL = """\
Escreva o post do LinkedIn EM INGLÊS sobre as principais notícias de IA e tecnologia \
de ontem ({date}). As notícias são:

{stories}

Contexto das últimas 2 semanas (NÃO repita esses tópicos principais):
{recent_context}

ÂNGULO OBRIGATÓRIO HOJE: USE O ÂNGULO #{style_num} conforme descrito no sistema.
A primeira frase tem que ser reconhecível como o ângulo #{style_num}.

Escreva em inglês nativo, não em inglês traduzido do português.

A notícia nº 1 da lista é a mais relevante do dia pelo ranking (cobertura em vários \
veículos, dinheiro envolvido, processo, regulação, lançamento grande ou polêmica em curso). \
O post ABRE por ela. Só desça na lista se a nº 1 estiver marcada como SÓ TÍTULO: aí abra \
pela primeira que tenha material e cite a nº 1 logo na primeira linha de menções.

Nunca dê o parágrafo principal para a notícia mais curiosa, mais recente ou mais fácil de \
comentar. Aquisição bilionária, processo judicial, decisão de regulador, modelo novo de \
peso e briga pública ganham de página de FAQ, de mudança de menu e de post de blog.

Escolha 1 ou 2 notícias ENTRE AS QUE TÊM MATERIAL para desenvolver com profundidade — número, nome e o que mudou — e cite as demais em uma linha só, se couberem. \
Um post que explica bem duas notícias vale mais que um que lista seis.

A lista pode trazer o MESMO acontecimento em duas entradas, com títulos diferentes de \
veículos diferentes. Trate as duas como uma notícia só: cite o fato uma vez, com o número \
mais preciso entre os dois títulos. Nunca escreva uma menção que descreve a própria lista \
("também chegou ao Hacker News junto com a reportagem sobre X").

O post tem no máximo 1400 caracteres. Conte antes de responder: o que passar disso é \
cortado por parágrafo inteiro na publicação, e o parágrafo que cai é o último — o das \
menções.

Responda APENAS com os blocos abaixo. Nenhuma linha antes do primeiro separador, \
nenhum comentário sobre o material, nenhuma pergunta.

Formate a resposta assim — use EXATAMENTE estes separadores:
---EN---
[post em inglês, sem hashtags]
---TAGS---
[4 a 5 hashtags em inglês, separadas por espaço, específicas ao tema do dia. Ex: #AI #OpenSourceLLM #SoftwareEngineering #Benchmarks]
---TEASER---
[chamada curtíssima em português, MÁXIMO 6 palavras, com o assunto concreto do post. Vai sobreposta numa foto. Sem ponto final, sem aspas, sem clickbait. Ex: Modelo aberto alcança GPT-4 em código]
---SUBTITLE---
[uma linha em português, MÁXIMO 12 palavras, com o FATO concreto da notícia principal — quem fez o quê. Complementa o teaser sem repeti-lo. Sem ponto final, sem aspas. Ex: Meta liberou os pesos do modelo sob licença permissiva]
---IMGQUERY---
[2 a 4 palavras EM INGLÊS descrevendo uma CENA VISUAL concreta e fotografável ligada ao tema principal, para buscar uma foto de banco de imagens. NÃO use nomes de marcas/empresas nem "logo". Prefira conceitos visuais reais. Ex: humanoid robot closeup / data center servers / glowing circuit board / developer coding laptop]
---END---
"""

_PT_USER_TMPL = """\
Abaixo está o post em inglês já fechado. Escreva a versão em português brasileiro DO MESMO \
post, que sai publicada logo abaixo dele.

POST EM INGLÊS:
{en_post}

MATERIAL DE ORIGEM (para conferir número, nome próprio e grafia — não acrescente nada que \
não esteja aqui nem no post em inglês):

{stories}

Regras desta versão:

1. MESMA QUANTIDADE DE PARÁGRAFOS, na mesma ordem. O inglês tem {paragraphs} parágrafos; \
o português tem {paragraphs}. Cada parágrafo do inglês vira um parágrafo em português.
2. Mesmos fatos, nenhum a mais e nenhum a menos. Se o inglês cita quatro notícias, o \
português cita as quatro, com os mesmos números.
3. Não é tradução literal. Escreva como quem pensa em português: ordem da frase, regência, \
conectivo e pontuação naturais do idioma. Onde o inglês usa uma construção sem equivalente, \
reescreva a frase mantendo o fato.
4. Nome de produto, empresa, benchmark e termo técnico consagrado ficam em inglês \
("open-source", "benchmark", "prompt"). O resto da frase, não. Nada de "performance" onde \
cabe "desempenho", nem "outage" onde cabe "queda".
5. Concordância e artigo corretos: "a Nvidia", "a Anthropic", "o Gemini, do Google".
6. Valor em dólar escreve-se "US$ 13 bilhões", não "$13 bilhões". Decimal com vírgula: \
"62,7%".
7. Máximo 1400 caracteres. Sem hashtag.

Responda APENAS com o bloco abaixo, nenhuma linha antes dele:
---PT---
[post em português]
---END---
"""


def _paragraph_count(text: str) -> int:
    return len([p for p in (text or "").split("\n\n") if p.strip()])


def _call_claude(
    system: str, user: str, max_tokens: int, prefill: str = "---EN---"
) -> tuple[str, str]:
    """Returns (text, stop_reason). The caller has to look at stop_reason:
    a response cut at max_tokens loses every block after the cut.

    The assistant turn is prefilled with the first separator. On 2026-09-01 the
    model opened with prose asking for fuller source material instead of the
    post, and that prose went out as the day's LinkedIn post. Starting the turn
    inside the format leaves no room for a preamble.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[
            {"role": "user", "content": user},
            {"role": "assistant", "content": prefill},
        ],
    )
    return f"{prefill}\n{msg.content[0].text.strip()}", (msg.stop_reason or "")


# Order matters: the parser slices the response between whichever tags are
# actually present, so a skipped tag widens the block before it instead of
# discarding it.
_BLOCK_TAGS = (
    "---EN---",
    "---PT---",
    "---TAGS---",
    "---TEASER---",
    "---SUBTITLE---",
    "---IMGQUERY---",
    "---END---",
)


def _parse_blocks(text: str) -> dict[str, str]:
    """Split the model answer into named blocks.

    Never falls back to positional guessing: the old `raw.split("---")[1]`
    fallback silently put the English body into the PT slot when the answer was
    truncated, and the post went out with the same text twice.
    """
    found = sorted(
        (idx, tag) for tag in _BLOCK_TAGS if (idx := text.find(tag)) != -1
    )
    blocks: dict[str, str] = {}
    for n, (idx, tag) in enumerate(found):
        start = idx + len(tag)
        end = found[n + 1][0] if n + 1 < len(found) else len(text)
        blocks[tag.strip("-")] = text[start:end].strip()
    return blocks


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
            f"{i}. [{s['source']}] {s['title']}",
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


def _opening_style_for_date(d: date_type) -> int:
    """Returns 1-8, cycles every 8 days based on day-of-year."""
    return (d.timetuple().tm_yday % 8) + 1


def _call_with_retry(system: str, user: str, max_tokens: int, prefill: str = "---EN---") -> str:
    """One call, retried once at a larger budget if the answer was cut."""
    raw, stop_reason = _call_claude(system, user, max_tokens, prefill)
    if stop_reason == "max_tokens":
        print("[content] Answer hit max_tokens — retrying with a larger budget")
        raw, stop_reason = _call_claude(system, user, MAX_TOKENS_RETRY, prefill)
    if stop_reason == "max_tokens":
        raise RuntimeError(
            "Claude answer truncated twice at max_tokens — refusing to post a "
            "half-generated digest. The next cron attempt retries today."
        )
    print(f"[content] Answer: {len(raw)} chars, stop_reason={stop_reason!r}")
    return raw


def _generate_pt(en_post: str, stories_text: str, dry_run: bool = False) -> str:
    """Write the Portuguese version from the finished English post.

    Returns "" rather than raising: an English-only post is worth publishing,
    a missing post is not.
    """
    if dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        return "[DRY RUN - post PT de exemplo]"

    wanted = _paragraph_count(en_post)
    prompt = _PT_USER_TMPL.format(
        en_post=en_post, stories=stories_text, paragraphs=wanted
    )

    print(f"[content] Generating the Portuguese version ({wanted} paragraphs)...")
    try:
        raw = _call_with_retry(_LINKEDIN_SYSTEM, prompt, MAX_TOKENS_PT, prefill="---PT---")
        pt = _parse_blocks(raw).get("PT", "")
    except Exception as e:
        print(f"[content] Portuguese call failed: {e}")
        return ""

    if pt and _paragraph_count(pt) < wanted:
        print(
            f"[content] PT came back with {_paragraph_count(pt)} paragraphs against "
            f"{wanted} in English — asking again"
        )
        retry_prompt = prompt + (
            f"\n\nATENÇÃO: a resposta anterior veio com menos parágrafos que o inglês. "
            f"Conte os parágrafos antes de responder: são {wanted}, separados por linha "
            f"em branco. Nenhuma notícia citada no inglês pode ficar de fora."
        )
        try:
            raw = _call_with_retry(
                _LINKEDIN_SYSTEM, retry_prompt, MAX_TOKENS_PT, prefill="---PT---"
            )
            retried = _parse_blocks(raw).get("PT", "")
            if retried and _paragraph_count(retried) >= _paragraph_count(pt):
                pt = retried
        except Exception as e:
            print(f"[content] Portuguese retry failed: {e}")

    if len(pt) > MAX_VERSION_CHARS:
        print(f"[content] PT ran {len(pt)} chars — trimming to whole sentences")
    return _trim_to_paragraph(pt, MAX_VERSION_CHARS)


def generate_content(
    stories: list[dict],
    history: dict,
    date_str: str,
    dry_run: bool = False,
) -> GeneratedContent:
    if not stories:
        raise ValueError("No stories to generate content from")

    main_story = stories[0]
    stories_text = _format_stories_for_prompt(stories)
    recent_ctx = _format_recent_context(history)

    post_date = date_type.fromisoformat(date_str)
    style_num = _opening_style_for_date(post_date)

    print(f"[content] Generating the English post — opening angle #{style_num}...")
    en_prompt = _EN_USER_TMPL.format(
        date=date_str,
        stories=stories_text,
        recent_context=recent_ctx,
        style_num=style_num,
    )

    # A dry run still generates real text: the copy is the thing worth previewing,
    # and Haiku costs a fraction of a cent. Only posting and history are skipped.
    if dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        print("[content] No ANTHROPIC_API_KEY — using placeholder copy")
        en_raw = (
            "---EN---\n[DRY RUN - EN post placeholder]\n"
            "---TAGS---\n#AI #Tech\n"
            "---TEASER---\nModelo aberto alcanca GPT-4 em codigo\n"
            "---SUBTITLE---\nMeta liberou os pesos sob licenca permissiva\n"
            "---IMGQUERY---\nhumanoid robot closeup\n---END---"
        )
    else:
        en_raw = _call_with_retry(_LINKEDIN_SYSTEM, en_prompt, MAX_TOKENS_EN)

    blocks = _parse_blocks(en_raw)
    linkedin_en = blocks.get("EN", "")
    hashtags = blocks.get("TAGS", "")
    image_teaser = blocks.get("TEASER", "")
    image_subtitle = blocks.get("SUBTITLE", "")
    image_query = blocks.get("IMGQUERY", "")

    missing = [k for k in ("EN", "TAGS", "TEASER", "SUBTITLE", "IMGQUERY") if not blocks.get(k)]
    if missing:
        print(f"[content] Blocks missing from the English answer: {', '.join(missing)}")

    if not linkedin_en:
        print("[content] Raw answer that could not be parsed:")
        print("-" * 60)
        print(en_raw[:2000])
        print("-" * 60)
        raise ValueError("Claude answer carried no EN block")

    if len(linkedin_en) > MAX_VERSION_CHARS:
        print(f"[content] EN ran {len(linkedin_en)} chars — trimming to whole sentences")
    linkedin_en = _trim_to_paragraph(linkedin_en, MAX_VERSION_CHARS)

    # The Portuguese version is written from the finished English post rather
    # than alongside it. Asking for both in one answer produced a PT version one
    # paragraph shorter than the EN one on two runs out of five, and the missing
    # paragraph was the one carrying the other stories.
    linkedin_pt = _generate_pt(linkedin_en, stories_text, dry_run=dry_run)

    # One language repeated twice reads as a bug to anyone scrolling the feed.
    # Drop the duplicate and publish the single version instead.
    if _same_text(linkedin_en, linkedin_pt):
        print("[content] EN and PT blocks are identical — publishing one version only")
        linkedin_pt = ""

    # Fallbacks so the image step never breaks. The subtitle exists to add a
    # fact the teaser does not carry, so an empty or echoing subtitle is dropped
    # rather than filled with the headline a second time.
    if not image_teaser:
        image_teaser = main_story.get("title", "")[:60]
    if _same_text(image_subtitle, image_teaser) or not image_subtitle:
        image_subtitle = ""
    if not image_query:
        image_query = "artificial intelligence technology"

    sources = list({s["source"] for s in stories})
    main_url = main_story.get("url", "")

    result = GeneratedContent(
        linkedin_pt=linkedin_pt,
        linkedin_en=linkedin_en,
        main_url=main_url,
        sources=sources,
        image_teaser=image_teaser,
        image_subtitle=image_subtitle,
        image_query=image_query,
        hashtags=hashtags,
    )

    if dry_run:
        print("\n--- LINKEDIN EN ---")
        print(result.linkedin_en)
        print("\n--- LINKEDIN PT ---")
        print(result.linkedin_pt)
        print(f"\n--- TAGS ---\n{result.hashtags}")
        print(f"--- TEASER ---\n{result.image_teaser}")
        print(f"--- SUBTITLE ---\n{result.image_subtitle}")
        print(
            f"--- CHARS --- EN {len(result.linkedin_en)} | PT {len(result.linkedin_pt)}"
            f"  --- PARAGRAPHS --- EN {_paragraph_count(result.linkedin_en)} | "
            f"PT {_paragraph_count(result.linkedin_pt)}"
        )

    return result


if __name__ == "__main__":
    import sys
    from news_fetcher import fetch_news, load_history
    from datetime import date

    stories = fetch_news(dry_run=True)
    history = load_history()
    content = generate_content(stories, history, str(date.today()), dry_run="--dry-run" in sys.argv)
    print("\n[OK] Content generated successfully")

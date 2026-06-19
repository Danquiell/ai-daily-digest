"""
Generates bilingual (PT-BR + EN) LinkedIn posts using Claude Haiku.
Opening style rotates deterministically by day-of-year (10 styles, cycles every 10 days).
"""
import os
import re
from dataclasses import dataclass
from datetime import date as date_type

import anthropic

MODEL = "claude-haiku-4-5-20251001"


@dataclass
class GeneratedContent:
    linkedin_pt: str
    linkedin_en: str
    main_url: str
    sources: list[str]
    image_teaser: str = ""
    image_subtitle: str = ""
    image_query: str = ""


_OPENING_STYLES = """\
ESTILOS DE ABERTURA (use EXATAMENTE o estilo do número indicado no prompt):
1. NÚMERO FRIO — Comece com um dado numérico bruto, sem introdução. Deixe o número falar sozinho. Ex: "340 bilhões de dólares em 18 meses."
2. CENA — Abra como numa cena de série: coloque o leitor dentro de um momento específico, sala, hora. Ex: "São 2h da manhã. Engenheiros do Google abrindo PR às pressas."
3. CONTRACORRENTE — Discorde abertamente do hype. Questione a narrativa que todo mundo está comprando. Ex: "Todo mundo comemorando. Mas leu a letra miúda?"
4. REAÇÃO BRUTA — Sua reação emocional sem filtro, curta e intensa. Ex: "Caí da cadeira." / "Não esperava isso hoje."
5. MEMÓRIA — Conecte a notícia a algo de semanas atrás que as pessoas esqueceram. Ex: "Lembra quando disseram que isso nunca aconteceria?"
6. PARADOXO — Comece com uma contradição aparente que o post vai resolver. Ex: "Um modelo que erra mais acerta melhor."
7. TELEGRAMA — Zero contexto. Vai direto ao fato em 1 linha como um recado urgente. Ex: "OpenAI comprou Jony Ive. É isso."
8. PROVOCAÇÃO — Uma afirmação deliberadamente incômoda que força o leitor a continuar. Ex: "Essa notícia vai envelhecer muito mal."
9. PERGUNTA INCÔMODA — Uma pergunta que o leitor não tem resposta mas não consegue ignorar. Ex: "Quanto do que você faz hoje ainda vai existir daqui 18 meses?"
10. BASTIDOR — Revele o detalhe que todo mundo ignorou no anúncio. Ex: "O detalhe que ninguém leu no comunicado de ontem:"
"""

_LINKEDIN_SYSTEM = """\
Você É Daniel Rios, estudante de tecnologia e entusiasta de IA no Brasil.
Escreve como se estivesse contando uma novidade pra um amigo próximo que também curte tech —
casual, direto, às vezes com ironia ou espanto genuíno.
Parece que você acabou de ver algo e precisou compartilhar. Nunca soa como IA ou post corporativo.

""" + _OPENING_STYLES + """
Regras absolutas:
- NUNCA use "Hoje em dia", "Na era da IA", "Com o avanço da", "É indiscutível", "No cenário atual"
- NUNCA use bullet points com hífen (-). Use → ou parágrafos fluidos
- Intercale dado concreto com reação pessoal: "...e honestamente? Isso muda o jogo."
- Tom: inteligente mas acessível, levemente provocativo, como quem sabe do assunto mas não esnoba
- Máximo 1300 caracteres por versão (PT e EN separadamente)
- Termine com pergunta curta e direta, específica ao tema — não genérica ("o que acham?")
- Versão PT: sem hashtags. Versão EN: 4-5 hashtags ao final
"""

_LINKEDIN_USER_TMPL = """\
Escreva UM post bilíngue do LinkedIn sobre as principais notícias de IA e tecnologia \
de ontem ({date}). As notícias são:

{stories}

Contexto das últimas 2 semanas (NÃO repita esses tópicos principais):
{recent_context}

ESTILO OBRIGATÓRIO HOJE: USE O ESTILO #{style_num} conforme descrito no sistema.
Não desobedeça este estilo. A abertura deve ser reconhecível como o estilo #{style_num}.

Formate a resposta assim — use EXATAMENTE estes separadores:
---PT---
[post em português]
---EN---
[post em inglês]
---TEASER---
[chamada curtíssima em português, MÁXIMO 6 palavras, que desperta curiosidade e dá vontade de abrir o post. Vai sobreposta numa foto. Sem ponto final, sem aspas. Ex: A IA que programa sozinha chegou]
---SUBTITLE---
[uma linha em português, MÁXIMO 12 palavras, com o FATO concreto da notícia principal — quem fez o quê. Complementa o teaser sem repeti-lo. Sem ponto final, sem aspas. Ex: OpenAI lançou um modelo que resolve tarefas de programação sozinho]
---IMGQUERY---
[2 a 4 palavras EM INGLÊS descrevendo uma CENA VISUAL concreta e fotografável ligada ao tema principal, para buscar uma foto de banco de imagens. NÃO use nomes de marcas/empresas nem "logo". Prefira conceitos visuais reais. Ex: humanoid robot closeup / data center servers / glowing circuit board / developer coding laptop]
---END---

Versão PT: sem hashtags.
Versão EN: 4-5 hashtags ao final (#AI #MachineLearning etc).
"""


def _call_claude(system: str, user: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text.strip()


def _extract_block(text: str, start_tag: str, end_tag: str) -> str:
    pattern = re.compile(
        rf"{re.escape(start_tag)}\s*(.*?)\s*{re.escape(end_tag)}",
        re.DOTALL,
    )
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _format_stories_for_prompt(stories: list[dict]) -> str:
    lines = []
    for i, s in enumerate(stories, 1):
        lines.append(
            f"{i}. [{s['source']}] {s['title']}\n"
            f"   URL: {s.get('url', 'N/A')}\n"
            f"   Resumo: {s.get('summary', 'Sem resumo disponível')[:150]}"
        )
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
    """Returns 1-10, cycles every 10 days based on day-of-year."""
    return (d.timetuple().tm_yday % 10) + 1


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

    print(f"[content] Generating LinkedIn post (PT-BR + EN) — opening style #{style_num}...")
    linkedin_prompt = _LINKEDIN_USER_TMPL.format(
        date=date_str,
        stories=stories_text,
        recent_context=recent_ctx,
        style_num=style_num,
    )

    if dry_run:
        linkedin_raw = (
            "---PT---\n🇧🇷 [DRY RUN — post PT de exemplo]\n---EN---\n"
            "🇺🇸 [DRY RUN — EN post example]\n#AI #Tech\n"
            "---TEASER---\nA IA que muda tudo chegou\n"
            "---SUBTITLE---\nOpenAI lançou um modelo que programa sozinho\n"
            "---IMGQUERY---\nhumanoid robot closeup\n---END---"
        )
    else:
        linkedin_raw = _call_claude(_LINKEDIN_SYSTEM, linkedin_prompt)

    linkedin_pt = _extract_block(linkedin_raw, "---PT---", "---EN---")
    linkedin_en = _extract_block(linkedin_raw, "---EN---", "---TEASER---")
    image_teaser = _extract_block(linkedin_raw, "---TEASER---", "---SUBTITLE---")
    image_subtitle = _extract_block(linkedin_raw, "---SUBTITLE---", "---IMGQUERY---")
    image_query = _extract_block(linkedin_raw, "---IMGQUERY---", "---END---")

    # Backward-compatible parse if the model skipped the SUBTITLE block.
    if not image_teaser:
        image_teaser = _extract_block(linkedin_raw, "---TEASER---", "---IMGQUERY---")

    # Backward-compatible parse if the model skipped the new EN/END boundary.
    if not linkedin_en:
        linkedin_en = _extract_block(linkedin_raw, "---EN---", "---END---")

    if not linkedin_pt or not linkedin_en:
        parts = linkedin_raw.split("---")
        linkedin_pt = parts[0].strip() if parts else linkedin_raw
        linkedin_en = parts[-1].strip() if len(parts) > 1 else linkedin_raw

    # Sensible fallbacks so the image step never breaks.
    if not image_teaser:
        image_teaser = main_story.get("title", "")[:60]
    if not image_subtitle:
        image_subtitle = main_story.get("title", "")[:90]
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
    )

    if dry_run:
        print("\n--- LINKEDIN PT ---")
        print(result.linkedin_pt)
        print("\n--- LINKEDIN EN ---")
        print(result.linkedin_en)

    return result


if __name__ == "__main__":
    import sys
    from news_fetcher import fetch_news, load_history
    from datetime import date

    stories = fetch_news(dry_run=True)
    history = load_history()
    content = generate_content(stories, history, str(date.today()), dry_run="--dry-run" in sys.argv)
    print("\n[OK] Content generated successfully")

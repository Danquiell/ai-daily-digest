"""
Generates bilingual (PT-BR + EN) posts for LinkedIn and Instagram
using Claude Haiku with prompts calibrated for human-sounding, emotional content.
"""
import json
import os
import re
from dataclasses import dataclass

import anthropic

MODEL = "claude-haiku-4-5-20251001"

@dataclass
class GeneratedContent:
    linkedin_pt: str
    linkedin_en: str
    instagram_caption_pt: str
    instagram_comment_en: str
    main_url: str
    sources: list[str]


_LINKEDIN_SYSTEM = """\
Você É Daniel Rios, estudante de tecnologia e entusiasta de IA no Brasil. \
Você escreve como se estivesse contando uma novidade pra um amigo próximo que também curte tech — \
casual, direto, às vezes com uma pitada de ironia ou espanto genuíno. \
Parece que você acabou de ver algo e precisou compartilhar. Nunca soa como IA ou como post corporativo.

Regras absolutas:
- NUNCA comece com "Hoje em dia", "Na era da IA", "Com o avanço da", "É indiscutível", "No cenário atual"
- Comece SEMPRE na primeira pessoa ou com uma observação pessoal: \
"Olha o que saiu ontem...", "Isso me pegou de surpresa:", "Não consigo parar de pensar nisso:", \
"Três coisas de ontem que valem seu tempo:", "Que semana, hein?", ou uma pergunta provocativa
- NUNCA use bullet points com hífen (-). Use → ou escreva em parágrafos fluidos
- Intercale dado concreto com reação pessoal: "...e honestamente? Isso muda o jogo."
- Tom: inteligente mas acessível, levemente provocativo, como quem sabe do assunto mas não esnoba
- Máximo 1300 caracteres por versão (PT e EN separadamente)
- Termine com pergunta curta e direta que convide comentário — não genérica ("o que acham?"), \
mas específica ao tema ("você usaria um modelo de 8B com guardrails no lugar de um 70B?")
- Versão PT: sem hashtags. Versão EN: 4-5 hashtags ao final
"""

_LINKEDIN_USER_TMPL = """\
Escreva UM post bilíngue do LinkedIn sobre as principais notícias de IA e tecnologia \
de ontem ({date}). As notícias são:

{stories}

Contexto das últimas 2 semanas (NÃO repita esses tópicos principais):
{recent_context}

Formate a resposta assim — use EXATAMENTE esses separadores:
---PT---
[post em português]
---EN---
[post em inglês]
---END---

Na versão PT: sem hashtags.
Na versão EN: 4-5 hashtags ao final (#AI #MachineLearning etc).
"""

_INSTAGRAM_SYSTEM = """\
Você é Daniel, criador de conteúdo tech brasileiro. Escreve para Instagram com \
linguagem leve, direta, emocional — como uma mensagem de voz transcrita, não um \
artigo. Foca na notícia mais impactante do dia de forma que qualquer pessoa entenda, \
mesmo sem saber nada de IA.

Regras:
- Caption PT: máximo 220 caracteres + 15 hashtags (linha separada)
- Comentário EN: máximo 200 caracteres + 4-5 hashtags
- Caption começa com emoji + frase de impacto
- Sempre termina com CTA curto ("Salva isso 👆", "Conta nos comentários 👇", etc.)
- Nunca use ponto final após hashtags
"""

_INSTAGRAM_USER_TMPL = """\
Notícia principal de ontem ({date}): {main_title}

Fonte: {source}

Escreva a caption do Instagram (PT-BR) e o primeiro comentário em inglês.

Formate assim:
---CAPTION---
[caption em português com emojis e hashtags]
---COMMENT---
[comentário em inglês com hashtags]
---END---
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

    print("[content] Generating LinkedIn post (PT-BR + EN)...")
    linkedin_prompt = _LINKEDIN_USER_TMPL.format(
        date=date_str,
        stories=stories_text,
        recent_context=recent_ctx,
    )

    if dry_run:
        linkedin_raw = (
            "---PT---\n🇧🇷 [DRY RUN — post PT de exemplo]\n---EN---\n"
            "🇺🇸 [DRY RUN — EN post example]\n#AI #Tech\n---END---"
        )
    else:
        linkedin_raw = _call_claude(_LINKEDIN_SYSTEM, linkedin_prompt)

    linkedin_pt = _extract_block(linkedin_raw, "---PT---", "---EN---")
    linkedin_en = _extract_block(linkedin_raw, "---EN---", "---END---")

    if not linkedin_pt or not linkedin_en:
        # Fallback: split by middle if tags weren't respected
        parts = linkedin_raw.split("---")
        linkedin_pt = parts[0].strip() if parts else linkedin_raw
        linkedin_en = parts[-1].strip() if len(parts) > 1 else linkedin_raw

    print("[content] Generating Instagram caption...")
    insta_prompt = _INSTAGRAM_USER_TMPL.format(
        date=date_str,
        main_title=main_story["title"],
        source=main_story["source"],
    )

    if dry_run:
        insta_raw = (
            "---CAPTION---\n🤖 [DRY RUN caption PT]\n\n#ia #tech\n"
            "---COMMENT---\n🇺🇸 [DRY RUN EN comment] #ai\n---END---"
        )
    else:
        insta_raw = _call_claude(_INSTAGRAM_SYSTEM, insta_prompt)

    instagram_caption_pt = _extract_block(insta_raw, "---CAPTION---", "---COMMENT---")
    instagram_comment_en = _extract_block(insta_raw, "---COMMENT---", "---END---")

    sources = list({s["source"] for s in stories})
    main_url = main_story.get("url", "")

    result = GeneratedContent(
        linkedin_pt=linkedin_pt,
        linkedin_en=linkedin_en,
        instagram_caption_pt=instagram_caption_pt,
        instagram_comment_en=instagram_comment_en,
        main_url=main_url,
        sources=sources,
    )

    if dry_run:
        print("\n--- LINKEDIN PT ---")
        print(result.linkedin_pt)
        print("\n--- LINKEDIN EN ---")
        print(result.linkedin_en)
        print("\n--- INSTAGRAM CAPTION ---")
        print(result.instagram_caption_pt)
        print("\n--- INSTAGRAM COMMENT (EN) ---")
        print(result.instagram_comment_en)

    return result


if __name__ == "__main__":
    import sys
    from news_fetcher import fetch_news, load_history

    stories = fetch_news(dry_run=True)
    history = load_history()
    from datetime import date
    content = generate_content(stories, history, str(date.today()), dry_run="--dry-run" in sys.argv)
    print("\n[OK] Content generated successfully")

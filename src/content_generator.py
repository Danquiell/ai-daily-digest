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
- Máximo 1300 caracteres por versão (EN e PT contados separadamente). Antes de responder, confira o tamanho; se passar, corte o parágrafo que carrega menos informação, não as frases com número.
- Termine com uma pergunta específica sobre uma decisão real que o leitor da área enfrenta, ou com o último fato concreto. Nunca "o que vocês acham?".
- Nenhuma das duas versões leva hashtag no corpo. As hashtags saem em bloco separado.
"""

_LINKEDIN_USER_TMPL = """\
Escreva UM post bilíngue do LinkedIn sobre as principais notícias de IA e tecnologia \
de ontem ({date}). As notícias são:

{stories}

Contexto das últimas 2 semanas (NÃO repita esses tópicos principais):
{recent_context}

ÂNGULO OBRIGATÓRIO HOJE: USE O ÂNGULO #{style_num} conforme descrito no sistema.
A primeira frase tem que ser reconhecível como o ângulo #{style_num}.

A versão EN é publicada primeiro e é a que a maioria vai ler. Escreva ela como texto \
original em inglês, não como tradução literal do português. A versão PT cobre os mesmos \
fatos e pode ter frases diferentes.

Escolha 1 ou 2 notícias da lista para desenvolver com profundidade — número, nome e o que \
mudou — e cite as demais em uma linha só, se couberem. Um post que explica bem duas notícias \
vale mais que um que lista seis.

Formate a resposta assim — use EXATAMENTE estes separadores:
---EN---
[post em inglês, sem hashtags]
---PT---
[post em português, sem hashtags]
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
    """Returns 1-8, cycles every 8 days based on day-of-year."""
    return (d.timetuple().tm_yday % 8) + 1


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

    print(f"[content] Generating LinkedIn post (EN + PT-BR) — opening angle #{style_num}...")
    linkedin_prompt = _LINKEDIN_USER_TMPL.format(
        date=date_str,
        stories=stories_text,
        recent_context=recent_ctx,
        style_num=style_num,
    )

    # A dry run still generates real text: the copy is the thing worth previewing,
    # and Haiku costs a fraction of a cent. Only posting and history are skipped.
    if dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        print("[content] No ANTHROPIC_API_KEY — using placeholder copy")
        linkedin_raw = (
            "---EN---\n[DRY RUN - EN post placeholder]\n"
            "---PT---\n[DRY RUN - post PT de exemplo]\n"
            "---TAGS---\n#AI #Tech\n"
            "---TEASER---\nModelo aberto alcanca GPT-4 em codigo\n"
            "---SUBTITLE---\nMeta liberou os pesos sob licenca permissiva\n"
            "---IMGQUERY---\nhumanoid robot closeup\n---END---"
        )
    else:
        linkedin_raw = _call_claude(_LINKEDIN_SYSTEM, linkedin_prompt)

    linkedin_en = _extract_block(linkedin_raw, "---EN---", "---PT---")
    linkedin_pt = _extract_block(linkedin_raw, "---PT---", "---TAGS---")
    hashtags = _extract_block(linkedin_raw, "---TAGS---", "---TEASER---")
    image_teaser = _extract_block(linkedin_raw, "---TEASER---", "---SUBTITLE---")
    image_subtitle = _extract_block(linkedin_raw, "---SUBTITLE---", "---IMGQUERY---")
    image_query = _extract_block(linkedin_raw, "---IMGQUERY---", "---END---")

    # Tolerate a skipped block by falling back to the next separator present.
    if not linkedin_pt:
        linkedin_pt = _extract_block(linkedin_raw, "---PT---", "---TEASER---")
    if not image_teaser:
        image_teaser = _extract_block(linkedin_raw, "---TEASER---", "---IMGQUERY---")

    if not linkedin_pt or not linkedin_en:
        parts = [p.strip() for p in linkedin_raw.split("---") if p.strip()]
        linkedin_en = linkedin_en or (parts[0] if parts else linkedin_raw)
        linkedin_pt = linkedin_pt or (parts[1] if len(parts) > 1 else linkedin_raw)

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
        print(f"--- CHARS --- EN {len(result.linkedin_en)} | PT {len(result.linkedin_pt)}")

    return result


if __name__ == "__main__":
    import sys
    from news_fetcher import fetch_news, load_history
    from datetime import date

    stories = fetch_news(dry_run=True)
    history = load_history()
    content = generate_content(stories, history, str(date.today()), dry_run="--dry-run" in sys.argv)
    print("\n[OK] Content generated successfully")

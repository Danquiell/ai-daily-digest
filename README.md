# AI Daily Digest

[![AI Daily Digest](https://github.com/Danquiell/ai-daily-digest/actions/workflows/daily_post.yml/badge.svg)](https://github.com/Danquiell/ai-daily-digest/actions/workflows/daily_post.yml)

Publica todo dia, às 6h (BRT), um post no **LinkedIn** com as notícias de IA do dia anterior:
de 1 a 4 imagens (o normal é uma) com foto real do assunto da notícia e uma legenda curta em inglês e em português.
Roda no GitHub Actions, sem servidor.

## Como funciona

1. O GitHub Actions dispara às 06:00 BRT.
2. `main.py` confere o token do LinkedIn. Token vencido encerra a execução aqui, antes de qualquer chamada paga.
3. `news_fetcher.py` busca as notícias das últimas 48 horas (RSS, Hacker News, Reddit), remove o que já saiu nos últimos 14 dias e ordena por relevância.
4. `content_generator.py` pede ao Claude Opus 5.5, em uma resposta estruturada em JSON, a legenda nos dois idiomas e, para cada imagem, o assunto a fotografar, o título e um fato. Cada número é conferido contra o texto das notícias; o que não está na fonte é removido.
5. `real_photo.py` busca na Wikimedia Commons uma foto com licença livre de cada assunto (a pessoa, o produto, a sede da empresa). Assunto sem foto fica sem imagem; a primeira imagem, sem foto, sai só com texto. Não há foto de banco de imagens.
6. `photo_cards.py` monta cada imagem em HTML (1080x1350, proporção 4:5) e o Chromium a renderiza em JPEG.
7. `linkedin_poster.py` publica: várias imagens em um post só, ou imagem única. Os links das fontes e o crédito de cada foto (autor e licença) vão no primeiro comentário, e `data/history.json` é atualizado.

Para ver o que seria publicado sem publicar:

```bash
gh workflow run daily_post.yml -f dry_run=true
```

As imagens, a legenda e o primeiro comentário ficam no artefato `linkedin-post-<id>` da execução.

Para pausar os posts agendados: `gh variable set POSTING_PAUSED --body true`. Para retomar: `gh variable delete POSTING_PAUSED`.

## Renovar o token do LinkedIn

O token vale 60 dias e o LinkedIn não fornece renovação automática para este tipo de app.
O workflow abre uma issue 7 dias antes do vencimento. Para renovar:

1. Gere um token em [linkedin.com/developers/tools/oauth/token-generator](https://www.linkedin.com/developers/tools/oauth/token-generator), com o app selecionado e os escopos `w_member_social`, `openid` e `profile`.
2. Na raiz do repositório, rode `python scripts/linkedin_auth.py --paste` e cole o token.

O script grava o segredo `LINKEDIN_ACCESS_TOKEN` e a variável `LINKEDIN_TOKEN_EXPIRES_AT` pelo GitHub CLI.

---

## Configuração

### Segredos e variáveis do repositório

Em **Settings → Secrets and variables → Actions**:

| Nome | Tipo | Valor |
|---|---|---|
| `ANTHROPIC_API_KEY` | segredo | Chave da API da Anthropic ([console.anthropic.com](https://console.anthropic.com)) |
| `LINKEDIN_ACCESS_TOKEN` | segredo | Token do LinkedIn, gravado por `scripts/linkedin_auth.py` |
| `LINKEDIN_PERSON_URN` | segredo | `urn:li:person:XXXXXXX` |
| `LINKEDIN_TOKEN_EXPIRES_AT` | variável | Data de vencimento do token, gravada pelo mesmo script |
| `POSTING_PAUSED` | variável | `true` pausa os posts agendados; opcional |

O commit do histórico usa o token embutido do GitHub Actions; não é preciso token pessoal.

### App do LinkedIn

1. Em [linkedin.com/developers](https://www.linkedin.com/developers/), crie um app.
2. Na aba **Products**, adicione **Share on LinkedIn** e **Sign In with LinkedIn using OpenID Connect**.
3. Gere o token e grave-o como descrito em "Renovar o token do LinkedIn".

O nome de usuário que aparece na imagem reserva fica em `LINKEDIN_USERNAME`, em `src/main.py`.

## Estrutura do projeto

```
ai-daily-digest/
├── .github/workflows/
│   ├── daily_post.yml          # post diário (06:00 BRT) e teste sem publicar
│   └── repost.yml              # apaga um post e publica de novo, manual
├── scripts/
│   └── linkedin_auth.py        # renova o token do LinkedIn
├── src/
│   ├── main.py                 # orquestra a execução
│   ├── news_fetcher.py         # RSS, Hacker News e Reddit; ranqueamento
│   ├── content_generator.py    # legenda e texto das imagens (Claude Opus 5.5)
│   ├── real_photo.py           # foto real do assunto (Wikimedia Commons)
│   ├── photo_cards.py          # imagens em HTML, renderizadas pelo Chromium
│   ├── image_generator.py      # card de texto usado se o Chromium falhar
│   ├── linkedin_poster.py      # API do LinkedIn
│   ├── repost.py               # usado por repost.yml
│   └── history_updater.py      # histórico e commit
├── data/history.json           # últimos 14 dias de posts
├── assets/fonts/               # Inter e Inter Tight
└── output/                     # arquivos gerados (fora do git)
```

## Regras do conteúdo

- Todo número vem do texto da notícia; o programa descarta o que não está lá.
- As fontes vão no primeiro comentário, com o crédito (autor e licença) de cada foto.
- Foto de pessoa só entra quando a notícia cita essa pessoa pelo nome.
- A imagem só existe para notícia que a legenda conta.
- O post cobre o fato corporativo, técnico, financeiro ou regulatório, sem vida pessoal.

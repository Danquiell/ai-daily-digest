# AI Daily Digest 🤖

[![AI Daily Digest](https://github.com/Danquiell/ai-daily-digest/actions/workflows/daily_post.yml/badge.svg)](https://github.com/Danquiell/ai-daily-digest/actions/workflows/daily_post.yml)

Postagem automática diária de novidades em IA e tecnologia no **LinkedIn** e **Instagram**,
às 6h (BRT), com linguagem natural e bilíngue (PT-BR + EN).
Roda 100% no GitHub Actions — sem servidor, sem máquina ligada.

**Custo:** ~R$3-7/mês (apenas Claude Haiku API).

---

## Como funciona

```
06:00 BRT → GitHub Actions dispara
   ↓
Busca notícias do dia anterior (RSS + Hacker News + Reddit)
   ↓
Remove duplicatas (janela de 14 dias)
   ↓
Claude Haiku gera post bilíngue (PT-BR + EN)
   ↓
Pillow cria card 1080x1080 para Instagram
   ↓
Posta no LinkedIn + Instagram
   ↓
Atualiza histórico e faz commit [skip ci]
```

---

## Setup — Passo a Passo

### 1. Criar repositório no GitHub

1. Acesse github.com → **New repository**
2. Nome sugerido: `ai-daily-digest`
3. Visibilidade: **Public** (GitHub Actions ilimitado)
4. Faça push deste projeto:

```bash
cd ~/ai-daily-digest
git init
git add .
git commit -m "feat: initial AI Daily Digest setup"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/ai-daily-digest.git
git push -u origin main
```

---

### 2. Anthropic API (Claude Haiku)

1. Acesse [console.anthropic.com](https://console.anthropic.com)
2. Crie uma conta e adicione créditos (mínimo $5 — dura meses)
3. Vá em **API Keys** → **Create Key**
4. Copie a chave → vai no Secret `ANTHROPIC_API_KEY`

---

### 3. LinkedIn Developer App

**Objetivo:** obter `LINKEDIN_ACCESS_TOKEN` e `LINKEDIN_PERSON_URN`.

1. Acesse [linkedin.com/developers](https://www.linkedin.com/developers/)
2. Clique em **Create App**
   - App name: `AI Daily Digest`
   - LinkedIn Page: sua página pessoal ou crie uma de empresa
   - App Logo: qualquer imagem
3. Na aba **Products**, solicite acesso a:
   - **Share on LinkedIn** (aprovação imediata)
   - **Sign In with LinkedIn using OpenID Connect**
4. Na aba **Auth**, copie o **Client ID** e **Client Secret**
5. Adicione Redirect URL: `https://www.linkedin.com/developers/tools/oauth/redirect`
6. **Gerar token de acesso:**
   - Vá em [linkedin.com/developers/tools/oauth/token-generator](https://www.linkedin.com/developers/tools/oauth/token-generator)
   - Selecione seu app
   - Marque os scopes: `r_liteprofile`, `w_member_social`
   - Clique **Request access token**
   - Copie o token (válido por 60 dias — veja seção de renovação)
7. **Obter Person URN:**
   ```bash
   curl -H "Authorization: Bearer SEU_TOKEN" \
     https://api.linkedin.com/v2/me
   ```
   Copie o campo `id` → seu URN será `urn:li:person:ID_AQUI`

> **Renovação do token LinkedIn:** O token expira em 60 dias.
> Para token de longa duração, você precisará configurar um servidor OAuth
> ou renovar manualmente a cada 60 dias no Token Generator.

---

### 4. Instagram (Meta Graph API)

**Pré-requisito:** converter conta para **Professional (Creator)**.

#### 4a. Converter conta Instagram para Creator

1. App Instagram → **Configurações** → **Tipo de conta**
2. Selecione **Conta Profissional** → **Criador de conteúdo**
3. Escolha uma categoria (ex: Blogueiro/a)

#### 4b. Criar página no Facebook (obrigatório)

1. Acesse facebook.com → **Criar Página**
2. Nome: mesmo nome do Instagram
3. Vincule ao Instagram: **Configurações da Página** → **Instagram** → **Conectar conta**

#### 4c. Criar Meta Developer App

1. Acesse [developers.facebook.com](https://developers.facebook.com)
2. **Meus Apps** → **Criar App**
   - Tipo: **Business**
   - App name: `AI Daily Digest`
3. Em **Adicionar produtos**, clique em **Configurar** no **Instagram Graph API**
4. Em **Funções** → **Testadores**, adicione sua conta Instagram

#### 4d. Obter tokens

1. Acesse o [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
2. Selecione seu app
3. **Gerar token de acesso** com as permissões:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_read_engagement`
4. Troque por token de longa duração (60 dias):
   ```
   https://graph.facebook.com/oauth/access_token
     ?grant_type=fb_exchange_token
     &client_id=SEU_APP_ID
     &client_secret=SEU_APP_SECRET
     &fb_exchange_token=TOKEN_CURTO
   ```
5. **Obter Instagram User ID:**
   ```
   https://graph.facebook.com/v19.0/me/accounts?access_token=SEU_TOKEN
   ```
   Pegue o `id` da página → depois:
   ```
   https://graph.facebook.com/v19.0/ID_DA_PAGINA?fields=instagram_business_account&access_token=SEU_TOKEN
   ```
   Copie `instagram_business_account.id` → este é seu `INSTAGRAM_USER_ID`

#### 4e. imgbb (upload de imagem gratuito)

A API do Instagram Graph exige URL pública para a imagem.
Usamos o [imgbb.com](https://imgbb.com) que tem API gratuita.

1. Crie conta em imgbb.com
2. Acesse [api.imgbb.com](https://api.imgbb.com/) → **Get API key**
3. Copie a chave → Secret `IMGBB_API_KEY`

---

### 5. GitHub PAT (para commit do histórico)

1. GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
2. **Generate new token (classic)**
   - Note: `AI Daily Digest bot`
   - Expiration: **No expiration** (ou 1 ano)
   - Scopes: marque `repo` (acesso completo ao repositório)
3. Copie o token → Secret `GH_TOKEN`

---

### 6. Configurar GitHub Secrets

No repositório GitHub:
**Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret | Valor |
|---|---|
| `ANTHROPIC_API_KEY` | Chave da Anthropic |
| `LINKEDIN_ACCESS_TOKEN` | Token do LinkedIn Developer |
| `LINKEDIN_PERSON_URN` | `urn:li:person:XXXXXXX` |
| `INSTAGRAM_USER_ID` | ID numérico do Instagram |
| `INSTAGRAM_ACCESS_TOKEN` | Token long-lived do Meta |
| `IMGBB_API_KEY` | Chave da imgbb API |
| `GH_TOKEN` | GitHub Personal Access Token |

---

### 7. Personalizar seu username

Edite `src/main.py`, linha com `username="@daniel.rios"` → troque pelo seu @ real.

---

### 8. Testar antes de ativar

Execute um dry-run diretamente no GitHub Actions:

1. Acesse a aba **Actions** no repositório
2. Clique em **AI Daily Digest** no menu lateral
3. Clique em **Run workflow** → marque **dry run** → **Run workflow**
4. Aguarde e veja os logs
5. O card de imagem gerado fica nos **Artifacts** do job

---

## Renovação de tokens

| Token | Validade | Como renovar |
|---|---|---|
| LinkedIn | 60 dias | Manualmente no Token Generator |
| Instagram | 60 dias | Automaticamente via workflow `refresh_instagram_token.yml` (a cada 50 dias) |
| GitHub PAT | Você escolhe | Manualmente nas configurações |

> O workflow de renovação do Instagram mostra o novo token nos logs.
> Você precisará copiar e atualizar o Secret manualmente.

---

## Estrutura do projeto

```
ai-daily-digest/
├── .github/workflows/
│   ├── daily_post.yml          # Job principal (06:00 BRT)
│   └── refresh_instagram_token.yml
├── src/
│   ├── main.py                 # Orquestrador
│   ├── news_fetcher.py         # RSS + HN + Reddit
│   ├── content_generator.py    # Claude Haiku
│   ├── image_generator.py      # Pillow card 1080x1080
│   ├── linkedin_poster.py      # LinkedIn API v2
│   ├── instagram_poster.py     # Instagram Graph API
│   └── history_updater.py      # Deduplicação + git commit
├── data/
│   └── history.json            # Últimos 14 dias de posts
├── assets/fonts/               # Fontes opcionais (Inter)
├── output/                     # Cards gerados (gitignored)
└── requirements.txt
```

---

## Licença e ética

- Apenas resumos e análises originais (uso transformativo)
- Fontes sempre citadas nos comentários
- Sem reprodução de artigos completos
- Sem conteúdo de fontes com paywall
- Pessoas mencionadas apenas com base em citações públicas verificadas

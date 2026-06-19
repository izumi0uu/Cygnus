"""
OAuth 2.1 router — Authorization Code + PKCE flow for Claude Desktop MCP.

Endpoints:
  GET  /.well-known/oauth-authorization-server  — server metadata (RFC 8414)
  POST /oauth/register                           — dynamic client registration (RFC 7591)
  GET  /oauth/authorize                          — show login form
  POST /oauth/authorize                          — submit credentials, issue code
  POST /oauth/token                              — exchange code for MCP token
"""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.auth_service import authenticate_employee
from app.services.oauth_service import OAuthService

# Two routers: one mounts at root (for .well-known), one at /oauth
wellknown_router = APIRouter()
router = APIRouter()


# ---------------------------------------------------------------------------
# OAuth server metadata (RFC 8414)
# ---------------------------------------------------------------------------

@wellknown_router.get("/.well-known/oauth-authorization-server")
async def oauth_metadata(request: Request):
    base = str(request.base_url).rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


# ---------------------------------------------------------------------------
# OAuth Protected Resource metadata (RFC 9728)
#
# Advertises that /mcp is an OAuth-protected resource and points clients
# (Claude Desktop, etc.) at the authorization server. Returned in the
# WWW-Authenticate header on 401 responses from /mcp so clients can
# auto-discover the OAuth flow.
# ---------------------------------------------------------------------------

@wellknown_router.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource_metadata(request: Request):
    base = str(request.base_url).rstrip("/")
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [],
        "resource_name": "Arkon MCP",
        "resource_documentation": f"{base}/docs",
    }


# RFC 9728 §3.1 encodes the resource path into the well-known URL: for
# resource https://host/mcp the metadata location is
# /.well-known/oauth-protected-resource/mcp. Serve the same document there
# so clients that follow that convention also find it.
@wellknown_router.get("/.well-known/oauth-protected-resource/mcp")
async def oauth_protected_resource_metadata_path_suffix(request: Request):
    return await oauth_protected_resource_metadata(request)


# ---------------------------------------------------------------------------
# Dynamic client registration (RFC 7591)
# ---------------------------------------------------------------------------

@router.post("/register", status_code=201)
async def register_client(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    name = body.get("client_name", "Claude Desktop")
    redirect_uris = body.get("redirect_uris", [])

    if not redirect_uris:
        raise HTTPException(status_code=400, detail="redirect_uris required")

    svc = OAuthService(db)
    client = await svc.register_client(name, redirect_uris)
    await db.commit()

    base = str(request.base_url).rstrip("/")
    return {
        "client_id": client.client_id,
        "client_name": client.name,
        "redirect_uris": client.redirect_uris,
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "registration_client_uri": f"{base}/oauth/register/{client.client_id}",
    }


# ---------------------------------------------------------------------------
# Authorization endpoint
# ---------------------------------------------------------------------------

def _login_form(
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    error: str = "",
) -> str:
    error_html = f'<p class="error">{error}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Arkon — Sign in</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400;500&family=Manrope:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #faf5ee;
      font-family: 'Manrope', ui-sans-serif, system-ui, sans-serif;
      color: #3a302a;
    }}
    .wrap {{
      width: 100%;
      max-width: 420px;
      padding: 0 24px;
    }}
    .brand {{
      text-align: center;
      margin-bottom: 32px;
    }}
    .brand h1 {{
      font-family: 'EB Garamond', ui-serif, Georgia, serif;
      font-size: 48px;
      font-weight: 400;
      color: #3a302a;
      line-height: 1;
      margin-bottom: 6px;
    }}
    .brand p {{
      font-size: 13px;
      color: #78706a;
    }}
    .card {{
      background: #f6f0e8;
      border: 1px solid #e5ddd2;
      border-radius: 14px;
      padding: 36px 32px;
      box-shadow: 0 2px 12px rgba(58,48,42,0.06);
    }}
    .card h2 {{
      font-size: 22px;
      font-weight: 500;
      color: #3a302a;
      margin-bottom: 24px;
    }}
    label {{
      display: block;
      font-size: 13px;
      font-weight: 500;
      color: #605850;
      margin-bottom: 6px;
    }}
    input[type=email], input[type=password] {{
      width: 100%;
      padding: 10px 14px;
      background: #faf5ee;
      border: 1px solid #d8d0c6;
      border-radius: 8px;
      color: #3a302a;
      font-family: 'Manrope', sans-serif;
      font-size: 14px;
      margin-bottom: 18px;
      outline: none;
      transition: border-color 0.15s, box-shadow 0.15s;
    }}
    input:focus {{
      border-color: #c2652a;
      box-shadow: 0 0 0 3px rgba(194,101,42,0.12);
    }}
    .error {{
      background: #fdf0ea;
      border: 1px solid #e8b49a;
      color: #9b3e12;
      border-radius: 8px;
      padding: 10px 14px;
      font-size: 13px;
      margin-bottom: 18px;
    }}
    button {{
      width: 100%;
      padding: 11px;
      background: #c2652a;
      border: none;
      border-radius: 8px;
      color: #fff;
      font-family: 'Manrope', sans-serif;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
      margin-top: 4px;
    }}
    button:hover {{ background: #a8521f; }}
    .footer {{
      text-align: center;
      font-size: 12px;
      color: #a09890;
      margin-top: 20px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="brand">
      <h1>Arkon</h1>
      <p>Enterprise AI Control Center</p>
    </div>
    <div class="card">
      <h2>Sign in</h2>
      {error_html}
      <form method="post">
        <input type="hidden" name="client_id" value="{client_id}">
        <input type="hidden" name="redirect_uri" value="{redirect_uri}">
        <input type="hidden" name="state" value="{state}">
        <input type="hidden" name="code_challenge" value="{code_challenge}">
        <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
        <label for="email">Email</label>
        <input id="email" type="email" name="email" placeholder="admin@arkon.local" required autofocus>
        <label for="password">Password</label>
        <input id="password" type="password" name="password" placeholder="Enter password" required>
        <button type="submit">Sign in</button>
      </form>
    </div>
    <p class="footer">Arkon v0.5 — On-Premise Deployment</p>
  </div>
</body>
</html>"""


@router.get("/authorize", response_class=HTMLResponse)
async def authorize_get(
    client_id: str,
    redirect_uri: str,
    response_type: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    state: str = "",
    db: AsyncSession = Depends(get_db),
):
    if response_type != "code":
        raise HTTPException(status_code=400, detail="unsupported_response_type")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="unsupported_code_challenge_method")

    svc = OAuthService(db)
    client = await svc.get_client(client_id)
    if not client:
        raise HTTPException(status_code=400, detail="invalid_client")
    if redirect_uri not in client.redirect_uris:
        raise HTTPException(status_code=400, detail="invalid_redirect_uri")

    return _login_form(client_id, redirect_uri, state, code_challenge, code_challenge_method)


@router.post("/authorize", response_class=HTMLResponse)
async def authorize_post(
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(""),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form("S256"),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    svc = OAuthService(db)
    client = await svc.get_client(client_id)
    if not client or redirect_uri not in client.redirect_uris:
        raise HTTPException(status_code=400, detail="invalid_client")

    employee = await authenticate_employee(db, email, password)
    if not employee:
        return HTMLResponse(
            content=_login_form(
                client_id, redirect_uri, state, code_challenge, code_challenge_method,
                error="Invalid email or password.",
            ),
            status_code=401,
        )

    code = await svc.create_auth_code(
        client_id=client_id,
        employee_id=employee.id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )
    await db.commit()

    params = {"code": code}
    if state:
        params["state"] = state
    return RedirectResponse(
        url=f"{redirect_uri}?{urlencode(params)}",
        status_code=302,
    )


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------

@router.post("/token")
async def token(
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: str = Form(...),
    client_id: str = Form(...),
    code_verifier: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="unsupported_grant_type")

    svc = OAuthService(db)
    access_token = await svc.exchange_code(
        code=code,
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )

    return JSONResponse({
        "access_token": access_token,
        "token_type": "bearer",
    })

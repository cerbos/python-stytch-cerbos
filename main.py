import json
import os
from dataclasses import dataclass, field

import uvicorn
from cerbos.sdk.client import CerbosClient
from cerbos.sdk.model import Principal, Resource, ResourceAction, ResourceList
from dataclasses_json import dataclass_json
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from stytch import Client
import logging

# from stytch.api.error import StytchError

MAGIC_LINK_URL = "http://localhost:3000/callback"  # This needs to match the `Login` and `Sign-up` URLs in the Stytch console
SESSION_DURATION_MINUTES = 60
SESSION_TOKEN_KEY = "session_token"
SESSION_ERROR_KEY = "errors"

CERBOS_HOST = "http://localhost:3592"
if (u := os.getenv("CERBOS_HOST")):
    CERBOS_HOST = f"http://{u}:3592"


logger = logging.getLogger()


app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="super-secret-key!")

templates = Jinja2Templates(directory="templates")

stytch_client = Client(
    project_id=os.environ["STYTCH_PROJECT_ID"],
    secret=os.environ["STYTCH_SECRET"],
    environment="test",
)


@dataclass_json
@dataclass
class TrustedMetadata:
    roles: set[str] = field(default_factory=set)


@dataclass_json
@dataclass
class User:
    user_id: str
    trusted_metadata: TrustedMetadata = field(default_factory=TrustedMetadata)

    @property
    def roles(self) -> set[str]:
        return self.trusted_metadata.roles

    def add_role(self, role: str):
        self.trusted_metadata.roles.add(role)


def prettify_json(data: dict) -> str:
    return json.dumps(data, sort_keys=False, indent=2)


def get_user_from_session(request: Request) -> User:
    token = request.session.get(SESSION_TOKEN_KEY)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": request.url_for("index")},
        )

    try:
        resp = stytch_client.sessions.authenticate(
            session_token=token,
        )
    except Exception:
        logger.exception("token error")
        request.session.pop(SESSION_TOKEN_KEY)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Session token invalid"
        )

    return User.from_dict(resp.json()["user"])


def push_role_to_stytch(user_id: str, role: str):
    u = User(user_id=user_id)
    u.add_role(role)
    try:
        resp = stytch_client.users.update(
            **u.to_dict(),
        )

        if resp.status_code != 200:
            raise Exception
    except Exception:
        print("Error updating role on User")


@app.get("/")
async def index(request: Request):
    if request.session.get(SESSION_TOKEN_KEY):
        return RedirectResponse(url="/user", status_code=status.HTTP_303_SEE_OTHER)

    ctx = {
        "request": request,
        "id": id,
    }
    if (error := request.session.pop(SESSION_ERROR_KEY, None)):
        ctx["errors"] = [error]

    return templates.TemplateResponse(
        "index.html",
        ctx,
    )


@app.post("/login_or_create_user")
async def login_or_create_user(
    request: Request, email: str = Form(), role: str = Form()
):
    try:
        resp = stytch_client.magic_links.email.login_or_create(
            email=email,
            login_magic_link_url=MAGIC_LINK_URL,
            signup_magic_link_url=MAGIC_LINK_URL,
        )

        if resp.status_code != 200:
            raise Exception

    except Exception:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "errors": ["Something went wrong sending magic link"]},
        )

    push_role_to_stytch(resp.json()["user_id"], role)

    return templates.TemplateResponse("email_sent.html", {"request": request, "id": id})


@app.route("/callback")
async def callback(request: Request):
    try:
        data = {
            "token": request.query_params["token"],
            "session_duration_minutes": SESSION_DURATION_MINUTES,
        }

        # If we already have a local session token, we send it with the authenticate request. Stripe
        # will refresh it if it's valid
        if (t := request.session.get(SESSION_TOKEN_KEY)) is not None:
            data[SESSION_TOKEN_KEY] = t

        resp = stytch_client.magic_links.authenticate(**data)

        if resp.status_code != 200:
            raise Exception

    # except StytchError as error:
    # # Handle Stytch errors here
    # # https://stytch.com/docs/api/errors/400

    except Exception:
        request.session[SESSION_ERROR_KEY] = "Error authenticating token" 
        return RedirectResponse(url=f"/logout")

    # Refresh the session token, if present (NOTE: it should always be present)
    if (t := resp.json().get(SESSION_TOKEN_KEY)) is not None:
        request.session[SESSION_TOKEN_KEY] = t

    return RedirectResponse(url="/user")


@app.get("/user", response_class=HTMLResponse)
async def user(request: Request, user: User = Depends(get_user_from_session)):
    principal = Principal(
        user.user_id,
        roles=user.roles,
    )

    # resources would usually be retrieved from your data store
    actions = {"read", "update", "delete"}
    resource_list = ResourceList(
        resources=[
            # This resource is owned by the user making the request
            ResourceAction(
                Resource(
                    "abc123",
                    "contact",
                    attr={
                        "owner_id": user.user_id,
                    },
                ),
                actions=actions,
            ),
            # This resource is owned by someone else
            ResourceAction(
                Resource(
                    "def456",
                    "contact",
                    attr={
                        "owner_id": "other_user_id",
                    },
                ),
                actions=actions,
            ),
        ]
    )

    with CerbosClient(host=CERBOS_HOST) as c:
        try:
            resp = c.check_resources(principal=principal, resources=resource_list)
            resp.raise_if_failed()
        except Exception:
            logger.exception("cerbos error")
            request.session.pop(SESSION_TOKEN_KEY, None)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized"
            )

    return templates.TemplateResponse(
        "user.html",
        {
            "user_id": user.user_id,
            "request": request,
            "cerbosPayload": prettify_json(
                {
                    "principal": principal.to_dict(),
                    "resource_list": resource_list.to_dict(),
                }
            ),
            "cerbosResponse": resp,
            "cerbosResponseJson": prettify_json(resp.to_dict()),
        },
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.pop(SESSION_TOKEN_KEY, None)
    return RedirectResponse(url="/")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=True)

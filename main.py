import json
from dataclasses import dataclass, field
import os

import uvicorn
from cerbos.sdk.client import CerbosClient
from cerbos.sdk.model import Principal, Resource, ResourceAction, ResourceList
from dataclasses_json import dataclass_json
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBearer
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from stytch import Client

# from stytch.api.error import StytchError

# MAGIC_LINK_URL = f"http://{HOST}:{PORT}/authenticate"
MAGIC_LINK_URL = "http://localhost:3000/callback"
SESSION_DURATION_MINUTES = 60
SESSION_TOKEN_KEY = "session_token"


stytch_client = Client(
    project_id=os.environ["STYTCH_PROJECT_ID"],
    secret=os.environ["STYTCH_SECRET"],
    environment="test",
)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="super-secret-key!")

bearer_scheme = HTTPBearer()

templates = Jinja2Templates(directory="templates")


@dataclass_json
@dataclass
class TrustedMetadata:
    roles: set[str] = field(default_factory=set)


@dataclass_json
@dataclass
class User:
    user_id: str
    trusted_metadata: TrustedMetadata = TrustedMetadata()

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
    return templates.TemplateResponse(
        "login_or_signup.html", {"request": request, "id": id}
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
        if (t := request.session.get(SESSION_TOKEN_KEY)) is not None:
            data["session_token"] = t
        resp = stytch_client.magic_links.authenticate(**data)
    # except StytchError as error:
    # # Handle Stytch errors here
    # # https://stytch.com/docs/api/errors/400
    # if error.error_type == "invalid_token":
    # print("Whoops! Try again?")
    except Exception:
        return templates.TemplateResponse(
            "index.html", {"request": request, "errors": ["Error authenticating token"]}
        )
        # raise HTTPException(
        # status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized"
        # )

    if resp.status_code != 200:
        print(resp)
        return "something went wrong authenticating token"

    if (t := resp.json().get("session_token")) is not None:
        request.session[SESSION_TOKEN_KEY] = t

    return RedirectResponse(url="/user")


@app.get("/user", response_class=HTMLResponse)
async def user(request: Request, user: User = Depends(get_user_from_session)):
    principal = Principal(
        user.user_id,
        roles=user.roles,
        policy_version="20210210",
        attr={
            "foo": "bar",
        },
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
                        "owner": user.user_id,
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
                        "owner": "other_user_id",
                    },
                ),
                actions=actions,
            ),
        ]
    )

    with CerbosClient(host="http://localhost:3592") as c:
        try:
            resp = c.check_resources(principal=principal, resources=resource_list)
            resp.raise_if_failed()
        except Exception:
            # TODO better handling
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
    uvicorn.run("main:app", port=3000, reload=True)

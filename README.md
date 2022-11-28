# python-stytch-cerbos

An example application of integrating [Cerbos](https://cerbos.dev) with a [FastAPI](https://fastapi.tiangolo.com/) server using [Stytch Magic Links](https://stytch.com/docs/magic-links) for authentication.

### Dependencies

- Docker for running the [Cerbos Policy Decision Point (PDP)](https://docs.cerbos.dev/cerbos/latest/installation/container.html) and the FastAPI server.
- A configured [Stytch Project](https://stytch.com/dashboard).

### Set up

1. Retrieve the project ID and secret from [here](https://stytch.com/dashboard/api-keys). Set the values to these env vars accordingly:
   ```sh
   STYTCH_PROJECT_ID
   STYTCH_SECRET
   ```

1. Create `Login` and `Sign-up` redirect URLs as `http://localhost:3000/callback`, in the [Redirect URLs page](https://stytch.com/dashboard/redirect-urls).

1. Run `docker-compose up -d` to fire up the Cerbos PDP instance and the FastAPI server.

1. Navigate to `http://localhost:3000`.

### Run through

When loading up the app, you'll be greeted by the login page. You can specify a "role" there; either `user` or `admin`. This ultimately sends a followup request (after login/creation) to Stytch to update the `trusted_metadata` field of the `user`, via [this API](https://stytch.com/docs/api/update-user). This is retrieved on subsequent authentication checks to retrieve the user roles when verifying identity via [this API](https://stytch.com/docs/api/session-auth).

**Note:** In production, you would handle the attribution of roles through some proper mechanism - the above is purely for demonstrative purposes.

### Policies

This example has a simple CRUD policy in place for a resource kind of `contact` - like a CRM system would have. The policy file can be found in the `cerbos/policies` folder [here](https://github.com/cerbos/python-cognito-cerbos/blob/main/cerbos/policies/contact.yaml).

Should you wish to experiment with this policy, you can <a href="https://play.cerbos.dev/p/g561543292ospj7w0zOrFx7H5DzhmLu2" target="_blank">try it in the Cerbos Playground</a>.

The policy expects one of two roles to be set on the principal - `admin` and `user`. These roles are authorized as follows:

| Action | User     | Admin |
| ------ | -------- | ----- |
| list   | Y        | Y     |
| read   | Y        | Y     |
| create | Y        | Y     |
| update | If owner | Y     |
| delete | If owner | Y     |

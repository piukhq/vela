# Vela

BPL Retailer Rewards Management API

## configurations

- create a `local.env` file in the root directory
- add your configurations based on the environmental variables required in `vela.core.config.Settings`

## running

- `poetry install`

### api run

- `poetry run python asgi.py` or `poetry run uvicorn asgi:app --port=8000`

### reward adjustment worker (rq)

- `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES poetry run python -m vela.core.cli task-worker`
- this worker deals with calling polaris to update an account holder's balance via an HTTP call.

> Running the command with the above environment variable is a work around for [this issue](https://github.com/rq/rq/issues/1418). It's a mac only issue to do with os.fork()'ing which rq.Worker utilises.

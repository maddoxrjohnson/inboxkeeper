import uvicorn

from inboxkeeper.api.app import create_app
from inboxkeeper.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()

#!/usr/bin/env python
from app.main import execute
from newsfeed_app_config import load_app_config
from dotenv import load_dotenv


def main():
    load_dotenv()
    execute(config=load_app_config())

if __name__ == "__main__":
    main()

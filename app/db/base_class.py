# mypy checks for sqlalchemy core 2.0 require sqlalchemy2-stubs
from sqlalchemy.orm import declarative_base  # type: ignore

Base = declarative_base()

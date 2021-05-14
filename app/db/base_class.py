# mypy checks for sqlalchemy core 2.0 require sqlalchemy2-stubs
from sqlalchemy import Column, Integer
from sqlalchemy.orm import as_declarative  # type: ignore


@as_declarative()
class Base:
    id = Column(Integer, primary_key=True, index=True)

"""Pydantic schemas for basjoo API.

This package hosts request/response DTOs that are too complex or
DB-coupled to live inline in endpoint modules. The Pydantic models in
here may import from ``models`` and ``core.encryption``; reverse imports
(models importing schemas) are not allowed.

Conventions:
    - Schemas named ``<Entity>Update`` are PATCH-style partial updates
      (all fields optional, ``None`` = "don't change this field").
    - Schemas named ``<Entity>Create`` are POST bodies.
    - Schemas named ``<Entity>Read`` are response shapes.
"""

__all__: list[str] = []

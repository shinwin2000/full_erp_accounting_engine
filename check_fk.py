from infrastructure.persistence_orm.base_model import Base

# Import semua model
import infrastructure.persistence_orm  # noqa

print(f"Total tables: {len(Base.metadata.tables)}")

broken = []
for table in Base.metadata.tables.values():
    for fk in table.foreign_keys:
        target_full = fk.target_fullname
        target_table = target_full.split(".")[0]
        if target_table not in Base.metadata.tables:
            broken.append(
                f"BROKEN: {table.name}.{fk.parent.name} -> {target_full}"
            )

if broken:
    print("\n❌ Broken FKs:")
    for b in broken:
        print(f"  {b}")
else:
    print("\n✅ All FKs valid")
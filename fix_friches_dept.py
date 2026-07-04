import duckdb

con = duckdb.connect('warehouse.duckdb')

# Afficher les vraies valeurs de code_commune pour comprendre
rows = con.execute("""
    SELECT site_id, commune, code_commune, departement
    FROM friches LIMIT 10
""").fetchall()
print("Valeurs actuelles :")
for r in rows:
    print(f"  site_id={r[0]}, commune={r[1]}, code_commune={r[2]}, dept={r[3]}")

# Le site_id contient le code dept ! Format : "95018_XXXX" ou "77192_XXXX"
# Extraire le dept depuis site_id
con.execute("""
    UPDATE friches
    SET departement = SPLIT_PART(site_id, '_', 1)[:2]
""")
con.commit()

depts = con.execute("""
    SELECT departement, COUNT(*) as n
    FROM friches
    WHERE departement IN ('77', '95')
    GROUP BY 1 ORDER BY 1
""").fetchall()
print("\nApres correction via site_id :")
for d in depts:
    print(f"  dept={d[0]}, n={d[1]}")

total = con.execute("SELECT COUNT(*) FROM friches WHERE departement IN ('77','95')").fetchone()[0]
print(f"\nTotal friches 77+95 : {total}")
con.close()

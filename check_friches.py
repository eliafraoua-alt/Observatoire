import duckdb

con = duckdb.connect('warehouse.duckdb')

print("Colonnes de la table friches :")
cols = con.execute("DESCRIBE friches").fetchall()
for c in cols:
    print(f"  {c[0]} ({c[1]})")

print(f"\nTotal : {con.execute('SELECT COUNT(*) FROM friches').fetchone()[0]}")

print("\nApercu :")
rows = con.execute("SELECT * FROM friches LIMIT 3").fetchall()
for r in rows:
    print(f"  {r[:8]}")

print("\nDepartements distincts :")
depts = con.execute("SELECT DISTINCT departement, COUNT(*) as n FROM friches GROUP BY 1").fetchall()
for d in depts:
    print(f"  dept={d[0]}, n={d[1]}")

con.close()

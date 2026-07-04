import duckdb

con = duckdb.connect('warehouse.duckdb')

# Voir les colonnes actuelles
cols = con.execute("DESCRIBE eau_indicateurs").fetchall()
print("Colonnes actuelles :")
for c in cols:
    print(f"  {c[0]} ({c[1]})")

# Supprimer et recréer avec le bon schéma
con.execute("DROP TABLE IF EXISTS eau_indicateurs")
con.execute("""
CREATE TABLE eau_indicateurs (
    service_id          VARCHAR,
    nom_service         VARCHAR,
    type_service        VARCHAR,
    commune             VARCHAR,
    code_commune        VARCHAR,
    departement         VARCHAR,
    annee               INTEGER,
    nb_habitants        DOUBLE,
    prix_eau_m3         DOUBLE,
    rendement_reseau    DOUBLE,
    indice_pertes       DOUBLE,
    taux_conformite     DOUBLE,
    taux_desserte       DOUBLE,
    conformite_eru      DOUBLE,
    source              VARCHAR,
    date_extraction     VARCHAR
)
""")
con.commit()
con.close()
print("\nTable recréée avec 16 colonnes")

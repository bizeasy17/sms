import psycopg2

DEV_DB = "smartinvestor_earnings_dev"
UAT_DB = "smartinvestor_earnings_uat"
DB_USER = "postgres"
DB_PASSWORD = "postgres"
DB_HOST = "127.0.0.1"
DB_PORT = "5432"


def connect(dbname: str):
    return psycopg2.connect(
        dbname=dbname,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
    )


def main():
    src = connect(DEV_DB)
    dst = connect(UAT_DB)
    try:
        with src.cursor() as s, dst.cursor() as d:
            s.execute("select id, name, created_at, updated_at from earnings_dim_industry order by id")
            industry_rows = s.fetchall()

            s.execute(
                "select id, ts_code, industry_id, created_at, updated_at "
                "from earnings_dim_corporation order by id"
            )
            corporation_rows = s.fetchall()

            d.execute("delete from earnings_dim_corporation")
            d.execute("delete from earnings_dim_industry")

            d.executemany(
                "insert into earnings_dim_industry (id, name, created_at, updated_at) "
                "values (%s, %s, %s, %s)",
                industry_rows,
            )
            d.executemany(
                "insert into earnings_dim_corporation (id, ts_code, industry_id, created_at, updated_at) "
                "values (%s, %s, %s, %s, %s)",
                corporation_rows,
            )

            d.execute("select pg_get_serial_sequence('earnings_dim_corporation', 'id')")
            seq_name = d.fetchone()[0]
            d.execute("select coalesce(max(id), 1) from earnings_dim_corporation")
            max_id = d.fetchone()[0]
            d.execute("select setval(%s, %s, true)", (seq_name, max_id))

        dst.commit()
        print(
            {
                "industry_rows": len(industry_rows),
                "corporation_rows": len(corporation_rows),
                "corporation_seq": seq_name,
                "corporation_seq_value": max_id,
            }
        )
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    main()

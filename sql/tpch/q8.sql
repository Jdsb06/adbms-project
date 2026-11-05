-- TPC-H Q8, using the official QGEN validation substitutions (-d 8).
-- SQLite adaptations: strftime instead of EXTRACT, ISO date string literals,
-- and 1.0 for real arithmetic with SQLite NUMERIC-affinity decimal columns.
-- This is the full Q8, including aggregation, rather than just its join core.
SELECT
    o_year,
    SUM(CASE WHEN nation = 'BRAZIL' THEN volume ELSE 0 END)
        / SUM(volume) AS mkt_share
FROM (
    SELECT
        CAST(strftime('%Y', o_orderdate) AS INTEGER) AS o_year,
        l_extendedprice * (1.0 - l_discount) AS volume,
        n2.n_name AS nation
    FROM
        part,
        supplier,
        lineitem,
        orders,
        customer,
        nation AS n1,
        nation AS n2,
        region
    WHERE
        p_partkey = l_partkey
        AND s_suppkey = l_suppkey
        AND l_orderkey = o_orderkey
        AND o_custkey = c_custkey
        AND c_nationkey = n1.n_nationkey
        AND n1.n_regionkey = r_regionkey
        AND r_name = 'AMERICA'
        AND s_nationkey = n2.n_nationkey
        AND o_orderdate BETWEEN '1995-01-01' AND '1996-12-31'
        AND p_type = 'ECONOMY ANODIZED STEEL'
) AS all_nations
GROUP BY o_year
ORDER BY o_year;

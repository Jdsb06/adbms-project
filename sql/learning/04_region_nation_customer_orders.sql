-- Extend the same chain by one reference; keep the region predicate fixed.
SELECT r.r_name, n.n_name, c.c_custkey, o.o_orderkey
FROM region AS r
JOIN nation AS n ON n.n_regionkey = r.r_regionkey
JOIN customer AS c ON c.c_nationkey = n.n_nationkey
JOIN orders AS o ON o.o_custkey = c.c_custkey
WHERE r.r_name = 'AMERICA';

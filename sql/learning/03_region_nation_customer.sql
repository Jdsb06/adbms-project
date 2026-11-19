-- Teaching example: compare a nation scan with an indexed extension of r.
SELECT r.r_name, n.n_name, c.c_custkey
FROM region AS r
JOIN nation AS n ON n.n_regionkey = r.r_regionkey
JOIN customer AS c ON c.c_nationkey = n.n_nationkey
WHERE r.r_name = 'AMERICA';

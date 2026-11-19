-- Two references still permit different loop orders and access methods.
SELECT r.r_name, n.n_name
FROM region AS r
JOIN nation AS n ON n.n_regionkey = r.r_regionkey
WHERE r.r_name = 'AMERICA';

-- Which category sold the most cases in 2025?
SELECT p.category,
       SUM(s.volume_cases) AS cases_2025
FROM sales AS s
JOIN products AS p USING (product_id)
WHERE s.month LIKE '2025-%'
GROUP BY p.category
ORDER BY cases_2025 DESC;

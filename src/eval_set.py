"""45 business questions with hand-checked correct answers, used to grade the assistant.

Two tiers:
  CORE (20): everyday questions. Both prompts scored 100% on these in the first live run,
             so on their own they cannot show whether the prompt's notes and examples help.
  HARD (15): written after that run, BEFORE any model saw them, aimed at the known ways
             text-to-SQL goes wrong: the wrong level of aggregation, relative dates,
             "best in each group", business definitions, and questions that look
             answerable but are not. Each has a "trap" note saying what a wrong answer does.
  HOLDOUT (5) and FRESH (5): see below. Used only to check that a fix generalises.

Rules for this set (each one is a question an interviewer may ask):
  - Written BEFORE looking at what the assistant produces, so the test is not shaped to pass.
  - None of these questions is one of the five worked examples in the prompt. Grading the
    assistant on questions it was shown the answer to would be like marking an exam with
    the questions you handed out in advance.
  - 7 of the 35 (3 core, 4 hard) cannot be answered from the data. The correct response is a refusal.
  - gold_sql is the reference query. It is checked by tests (it runs and returns rows) and
    by hand. The grader compares the assistant's RESULT with the gold result, not the SQL
    text, because many different queries give the same correct answer.
  - "kind" groups the questions so failures can be traced to a type of question.
"""

CORE = [
    # ---------------------------------------------------------------- simple totals
    {"id": "q01", "kind": "total", "question": "What was total revenue in 2025?",
     "gold_sql": "SELECT ROUND(SUM(revenue_gbp), 2) AS revenue FROM sales WHERE month LIKE '2025-%'"},
    {"id": "q02", "kind": "total", "question": "How many cases did we sell in 2023?",
     "gold_sql": "SELECT SUM(volume_cases) AS cases FROM sales WHERE month LIKE '2023-%'"},
    {"id": "q03", "kind": "total", "question": "How many products are still listed today?",
     "gold_sql": "SELECT COUNT(*) AS products FROM products WHERE delist_after IS NULL"},
    # ---------------------------------------------------------------- rankings
    {"id": "q04", "kind": "ranking", "question": "Which category had the highest revenue in 2025?",
     "gold_sql": "SELECT p.category FROM sales s JOIN products p USING (product_id) "
                 "WHERE s.month LIKE '2025-%' GROUP BY p.category "
                 "ORDER BY SUM(s.revenue_gbp) DESC LIMIT 1"},
    {"id": "q05", "kind": "ranking", "question": "What were the top 5 products by volume in 2025?",
     "gold_sql": "SELECT p.product_name FROM sales s JOIN products p USING (product_id) "
                 "WHERE s.month LIKE '2025-%' GROUP BY p.product_name "
                 "ORDER BY SUM(s.volume_cases) DESC LIMIT 5"},
    {"id": "q06", "kind": "ranking", "question": "Which region sold the fewest cases in Q1 2025?",
     "gold_sql": "SELECT r.region_name FROM sales s JOIN regions r USING (region_id) "
                 "WHERE s.month BETWEEN '2025-01' AND '2025-03' GROUP BY r.region_name "
                 "ORDER BY SUM(s.volume_cases) ASC LIMIT 1"},
    {"id": "q07", "kind": "ranking", "question": "Which month of 2024 had the highest sales volume?",
     "gold_sql": "SELECT month FROM sales WHERE month LIKE '2024-%' GROUP BY month "
                 "ORDER BY SUM(volume_cases) DESC LIMIT 1"},
    # ---------------------------------------------------------------- breakdowns
    {"id": "q08", "kind": "breakdown", "question": "Show revenue by region for 2024.",
     "gold_sql": "SELECT r.region_name, ROUND(SUM(s.revenue_gbp), 2) AS revenue "
                 "FROM sales s JOIN regions r USING (region_id) WHERE s.month LIKE '2024-%' "
                 "GROUP BY r.region_name"},
    {"id": "q09", "kind": "breakdown", "question": "Show total volume for each month of 2025.",
     "gold_sql": "SELECT month, SUM(volume_cases) AS cases FROM sales WHERE month LIKE '2025-%' "
                 "GROUP BY month"},
    {"id": "q10", "kind": "breakdown", "question": "What was revenue by category in Q4 2025?",
     "gold_sql": "SELECT p.category, ROUND(SUM(s.revenue_gbp), 2) AS revenue "
                 "FROM sales s JOIN products p USING (product_id) "
                 "WHERE s.month BETWEEN '2025-10' AND '2025-12' GROUP BY p.category"},
    # ---------------------------------------------------------------- growth and ratios
    {"id": "q11", "kind": "growth", "question": "By what percent did Energy revenue grow from 2024 to 2025?",
     "gold_sql": "SELECT ROUND((SUM(CASE WHEN s.month LIKE '2025-%' THEN s.revenue_gbp END) "
                 "- SUM(CASE WHEN s.month LIKE '2024-%' THEN s.revenue_gbp END)) * 100.0 "
                 "/ SUM(CASE WHEN s.month LIKE '2024-%' THEN s.revenue_gbp END), 1) AS growth_pct "
                 "FROM sales s JOIN products p USING (product_id) WHERE p.category = 'Energy'"},
    {"id": "q12", "kind": "growth",
     "question": "How did Carbonated volume in the South in July 2024 compare with July 2023, in percent?",
     "gold_sql": "SELECT ROUND((SUM(CASE WHEN s.month = '2024-07' THEN s.volume_cases END) "
                 "- SUM(CASE WHEN s.month = '2023-07' THEN s.volume_cases END)) * 100.0 "
                 "/ SUM(CASE WHEN s.month = '2023-07' THEN s.volume_cases END), 1) AS change_pct "
                 "FROM sales s JOIN products p USING (product_id) JOIN regions r USING (region_id) "
                 "WHERE p.category = 'Carbonated' AND r.region_name = 'South'"},
    {"id": "q13", "kind": "ratio",
     "question": "What share of 2025 revenue came from sales on promotion, in percent?",
     "gold_sql": "SELECT ROUND(SUM(CASE WHEN on_promotion = 1 THEN revenue_gbp ELSE 0 END) * 100.0 "
                 "/ SUM(revenue_gbp), 1) AS promo_share_pct FROM sales WHERE month LIKE '2025-%'"},
    {"id": "q14", "kind": "ratio",
     "question": "What was the average revenue per case for each category in 2025?",
     "gold_sql": "SELECT p.category, ROUND(SUM(s.revenue_gbp) / SUM(s.volume_cases), 2) AS gbp_per_case "
                 "FROM sales s JOIN products p USING (product_id) WHERE s.month LIKE '2025-%' "
                 "GROUP BY p.category"},
    # ---------------------------------------------------------------- the product and promotion tables
    {"id": "q15", "kind": "lookup", "question": "Which products were launched in 2024?",
     "gold_sql": "SELECT product_name FROM products WHERE launch_month LIKE '2024-%'"},
    {"id": "q16", "kind": "lookup", "question": "Which product was delisted, and what was its last month on sale?",
     "gold_sql": "SELECT product_name, delist_after FROM products WHERE delist_after IS NOT NULL"},
    {"id": "q17", "kind": "lookup", "question": "How many promotions were planned in 2025, and what was their average discount?",
     "gold_sql": "SELECT COUNT(*) AS promotions, ROUND(AVG(discount_pct), 1) AS avg_discount_pct "
                 "FROM promotions WHERE month LIKE '2025-%'"},
    # ---------------------------------------------------------------- must refuse
    {"id": "q18", "kind": "refuse", "question": "Which customer bought the most Cola 330ml in 2025?",
     "gold_sql": None},
    {"id": "q19", "kind": "refuse", "question": "How much did hot weather increase Water sales last summer?",
     "gold_sql": None},
    {"id": "q20", "kind": "refuse", "question": "How many stores stock Energy Original 250ml?",
     "gold_sql": None},
]

HARD = [
    # ---------------------------------------------------------------- level of aggregation
    {"id": "h01", "kind": "aggregation-level",
     "question": "What was the average monthly volume for each region in 2025?",
     "trap": "AVG(volume_cases) averages product rows (about 1,400 cases), not monthly region totals (30,000 to 52,000).",
     "gold_sql": "SELECT r.region_name, ROUND(SUM(s.volume_cases) / 12.0, 1) AS avg_monthly_cases "
                 "FROM sales s JOIN regions r USING (region_id) WHERE s.month LIKE '2025-%' "
                 "GROUP BY r.region_name"},
    {"id": "h02", "kind": "aggregation-level",
     "question": "How many different products were promoted in 2025?",
     "trap": "COUNT(*) counts promotion rows (product x region x month), not products.",
     "gold_sql": "SELECT COUNT(DISTINCT product_id) AS products FROM promotions WHERE month LIKE '2025-%'"},
    {"id": "h03", "kind": "aggregation-level",
     "question": "What share of the South's 2025 volume came from Carbonated drinks, in percent?",
     "trap": "The denominator must be all South volume, not all volume or all Carbonated volume.",
     "gold_sql": "SELECT ROUND(SUM(CASE WHEN p.category = 'Carbonated' THEN s.volume_cases ELSE 0 END) "
                 "* 100.0 / SUM(s.volume_cases), 1) AS carbonated_share_pct "
                 "FROM sales s JOIN products p USING (product_id) JOIN regions r USING (region_id) "
                 "WHERE r.region_name = 'South' AND s.month LIKE '2025-%'"},
    # ---------------------------------------------------------------- time
    {"id": "h04", "kind": "time",
     "question": "What was total revenue over the last three months?",
     "trap": "'Last' means the latest data (2025-10 to 2025-12), not date('now'), which finds nothing.",
     "gold_sql": "SELECT ROUND(SUM(revenue_gbp), 2) AS revenue FROM sales "
                 "WHERE month BETWEEN '2025-10' AND '2025-12'"},
    {"id": "h05", "kind": "time",
     "question": "Which month in 2025 had the biggest month-on-month increase in total volume?",
     "trap": "Needs the previous month's total (a window function or self-join), not the largest month.",
     "gold_sql": "WITH m AS (SELECT month, SUM(volume_cases) AS cases FROM sales GROUP BY month) "
                 "SELECT month FROM (SELECT month, cases - LAG(cases) OVER (ORDER BY month) AS change "
                 "FROM m) WHERE month LIKE '2025-%' ORDER BY change DESC LIMIT 1"},
    {"id": "h06", "kind": "time",
     "question": "Which products sold in every month of 2025?",
     "trap": "The delisted product stops after June; listing all products is wrong.",
     "gold_sql": "SELECT p.product_name FROM sales s JOIN products p USING (product_id) "
                 "WHERE s.month LIKE '2025-%' GROUP BY p.product_name "
                 "HAVING COUNT(DISTINCT s.month) = 12"},
    # ---------------------------------------------------------------- best within each group
    {"id": "h07", "kind": "top-per-group",
     "question": "What was the best-selling product by volume in each region in 2025?",
     "trap": "One winner per region (3 rows): ORDER BY ... LIMIT 1 gives one row in total.",
     "gold_sql": "WITH t AS (SELECT r.region_name, p.product_name, SUM(s.volume_cases) AS cases, "
                 "RANK() OVER (PARTITION BY r.region_name ORDER BY SUM(s.volume_cases) DESC) AS rk "
                 "FROM sales s JOIN products p USING (product_id) JOIN regions r USING (region_id) "
                 "WHERE s.month LIKE '2025-%' GROUP BY r.region_name, p.product_name) "
                 "SELECT region_name, product_name FROM t WHERE rk = 1"},
    {"id": "h08", "kind": "top-per-group",
     "question": "Which category grew fastest in revenue from 2023 to 2025, and by how much in percent?",
     "trap": "Growth per category over two years, then the top one.",
     "gold_sql": "WITH y AS (SELECT p.category, "
                 "SUM(CASE WHEN s.month LIKE '2023-%' THEN s.revenue_gbp END) AS r23, "
                 "SUM(CASE WHEN s.month LIKE '2025-%' THEN s.revenue_gbp END) AS r25 "
                 "FROM sales s JOIN products p USING (product_id) GROUP BY p.category) "
                 "SELECT category, ROUND((r25 - r23) * 100.0 / r23, 1) AS growth_pct FROM y "
                 "ORDER BY growth_pct DESC LIMIT 1"},
    # ---------------------------------------------------------------- business definitions
    {"id": "h09", "kind": "definition",
     "question": "Excluding products launched in 2024, how did total volume change from 2024 to 2025, in percent?",
     "trap": "A like-for-like filter on launch_month, applied to both years.",
     "gold_sql": "SELECT ROUND((SUM(CASE WHEN s.month LIKE '2025-%' THEN s.volume_cases END) "
                 "- SUM(CASE WHEN s.month LIKE '2024-%' THEN s.volume_cases END)) * 100.0 "
                 "/ SUM(CASE WHEN s.month LIKE '2024-%' THEN s.volume_cases END), 1) AS change_pct "
                 "FROM sales s JOIN products p USING (product_id) WHERE p.launch_month NOT LIKE '2024-%'"},
    {"id": "h10", "kind": "definition",
     "question": "What was the average discount on Energy promotions in 2025?",
     "trap": "Discounts live in the promotions table; sales has only a 0/1 flag.",
     "gold_sql": "SELECT ROUND(AVG(pr.discount_pct), 1) AS avg_discount_pct FROM promotions pr "
                 "JOIN products p USING (product_id) WHERE p.category = 'Energy' AND pr.month LIKE '2025-%'"},
    {"id": "h11", "kind": "definition",
     "question": "For products that have ever been promoted, what were average cases per product, region "
                 "and month in 2025, on promotion versus not on promotion?",
     "trap": "Restrict to products that were ever promoted, then split by on_promotion (2 rows). "
             "Only the averages are graded, so labels such as 'Yes'/'No' are fine.",
     "gold_sql": "SELECT ROUND(AVG(volume_cases), 1) AS avg_cases FROM sales "
                 "WHERE month LIKE '2025-%' AND product_id IN (SELECT product_id FROM promotions) "
                 "GROUP BY on_promotion"},
    # ---------------------------------------------------------------- looks answerable, is not
    {"id": "h12", "kind": "refuse",
     "question": "What was our market share in Carbonated drinks in 2025?",
     "trap": "Needs the whole market's sales; we only have our own.", "gold_sql": None},
    {"id": "h13", "kind": "refuse",
     "question": "Which promotion gave the best return on investment?",
     "trap": "ROI needs the cost of each promotion; the data has discounts but no costs.", "gold_sql": None},
    {"id": "h14", "kind": "refuse",
     "question": "What will total volume be in March 2026?",
     "trap": "A forecast, not a lookup: the database ends in 2025-12.", "gold_sql": None},
    {"id": "h15", "kind": "refuse",
     "question": "Why did Carbonated sales in the South drop in July 2024?",
     "trap": "The data shows the drop, not its cause.", "gold_sql": None},
]

# HOLDOUT: written after the second run, BEFORE the output-rule fix was tested, and never
# used to change the prompt. The fix was aimed at questions that need interpreting, so these
# five are of that type: if the fix only works on h04 and h06, it will show here.
HOLDOUT = [
    {"id": "x01", "kind": "time", "question": "What was revenue in the most recent full year?",
     "gold_sql": "SELECT ROUND(SUM(revenue_gbp), 2) AS revenue FROM sales WHERE month LIKE '2025-%'"},
    {"id": "x02", "kind": "time", "question": "Which products have we stopped selling?",
     "gold_sql": "SELECT product_name FROM products WHERE delist_after IS NOT NULL"},
    {"id": "x03", "kind": "definition", "question": "What is our biggest region?",
     "gold_sql": "SELECT r.region_name FROM sales s JOIN regions r USING (region_id) "
                 "GROUP BY r.region_name ORDER BY SUM(s.revenue_gbp) DESC LIMIT 1"},
    {"id": "x04", "kind": "time",
     "question": "How did revenue in the latest quarter compare with the same quarter a year earlier, in percent?",
     "gold_sql": "SELECT ROUND((SUM(CASE WHEN month BETWEEN '2025-10' AND '2025-12' THEN revenue_gbp END) "
                 "- SUM(CASE WHEN month BETWEEN '2024-10' AND '2024-12' THEN revenue_gbp END)) * 100.0 "
                 "/ SUM(CASE WHEN month BETWEEN '2024-10' AND '2024-12' THEN revenue_gbp END), 1) "
                 "AS growth_pct FROM sales"},
    {"id": "x05", "kind": "time", "question": "Which products are new, meaning launched after we started recording?",
     "gold_sql": "SELECT product_name FROM products WHERE launch_month > '2023-01'"},
]

# FRESH: the first holdout (x01-x05) was used once, to reject the prompt-only fix, so it is no
# longer untouched. These five were written before the tool-call fix was ever run, and are
# the clean test of it. Same type: questions that need interpreting.
FRESH = [
    {"id": "y01", "kind": "time", "question": "How many cases did we sell last year?",
     "gold_sql": "SELECT SUM(volume_cases) AS cases FROM sales WHERE month LIKE '2025-%'"},
    {"id": "y02", "kind": "time", "question": "Which products are on promotion at the moment?",
     "gold_sql": "SELECT DISTINCT p.product_name FROM promotions pr JOIN products p USING (product_id) "
                 "WHERE pr.month = '2025-12'"},
    {"id": "y03", "kind": "time", "question": "What was our best month ever for revenue?",
     "gold_sql": "SELECT month FROM sales GROUP BY month ORDER BY SUM(revenue_gbp) DESC LIMIT 1"},
    {"id": "y04", "kind": "time", "question": "How many Water products do we sell now?",
     "gold_sql": "SELECT COUNT(DISTINCT s.product_id) AS products FROM sales s "
                 "JOIN products p USING (product_id) WHERE p.category = 'Water' AND s.month = '2025-12'"},
    {"id": "y05", "kind": "definition",
     "question": "How much revenue did our newest products bring in last year?",
     "gold_sql": "SELECT ROUND(SUM(s.revenue_gbp), 2) AS revenue FROM sales s JOIN products p "
                 "USING (product_id) WHERE p.launch_month LIKE '2024-%' AND s.month LIKE '2025-%'"},
]

QUESTIONS = ([q | {"tier": "core"} for q in CORE] + [q | {"tier": "hard"} for q in HARD]
             + [q | {"tier": "holdout"} for q in HOLDOUT] + [q | {"tier": "fresh"} for q in FRESH])

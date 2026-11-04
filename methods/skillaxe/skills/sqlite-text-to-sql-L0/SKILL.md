---
name: "sqlite-text-to-sql"
description: "A reusable SQLite Text-to-SQL skill that translates natural language questions into SQL queries. This skill is useful for converting user requests into executable SQL commands based on database schemas, enabling automated data retrieval and analysis."
---

## Text-to-SQL Translation Skill for SQLite

This skill provides a structured approach to convert natural language questions into SQL queries tailored for SQLite databases. It guides the user through understanding the schema, identifying key entities and relationships, and constructing accurate SQL statements.

### When to Use
- When you need to automate data retrieval from a SQLite database based on user questions.
- When designing systems that require natural language interfaces to databases.
- To facilitate quick prototyping of SQL queries from plain language.

### Procedure
1. **Understand the Schema**: Familiarize yourself with the tables, columns, and relationships in the database schema.
2. **Identify Entities and Attributes**: Determine which tables and columns are relevant to the question.
3. **Extract Key Conditions**: Find conditions, filters, or specific values mentioned in the question.
4. **Determine the Type of Query**: Decide whether to SELECT data, COUNT, or perform aggregations.
5. **Construct the SQL Query**:
   - Use `SELECT` to specify columns or aggregate functions.
   - Use `FROM` to specify the main table.
   - Use `JOIN` if multiple tables are involved, based on foreign keys.
   - Use `WHERE` to filter data based on conditions.
   - Use `ORDER BY` for sorting if needed.
   - Use `LIMIT` if the question specifies a subset.

### Illustrative Examples
- Question: "How many female students live in Smith Hall?"
  ```sql
  SELECT COUNT(*)
  FROM Student
  JOIN Lives_in ON Student.StuID = Lives_in.stuid
  JOIN Dorm ON Lives_in.dormid = Dorm.dormid
  WHERE Student.Sex = 'F' AND Dorm.dorm_name = 'Smith Hall';
  ```
- Question: "What are the names and URLs of images, sorted alphabetically?"
  ```sql
  SELECT image_name, image_url
  FROM Images
  ORDER BY image_name ASC;
  ```
- Question: "With which payment method were the least number of payments processed?"
  ```sql
  SELECT Payment_Method_Code, COUNT(*) AS count_payments
  FROM Payments
  GROUP BY Payment_Method_Code
  ORDER BY count_payments ASC
  LIMIT 1;
  ```

### Usage Patterns
- Use pattern matching (`LIKE`, `IN`) for textual conditions.
- Use aggregate functions (`COUNT`, `SUM`, `AVG`) for summarization.
- Use `JOIN` clauses to combine data from related tables.
- Use subqueries for complex conditions or nested queries.

### Setup
- Ensure the SQLite environment is set up with the relevant database and schema loaded.
- Familiarize yourself with foreign key relationships to construct proper joins.

This skill serves as a foundational template for translating natural language questions into SQL queries in SQLite, adaptable to various schemas and question types.

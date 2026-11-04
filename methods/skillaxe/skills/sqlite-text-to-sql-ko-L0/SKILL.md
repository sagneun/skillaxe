---
name: "sqlite-text-to-sql-ko"
description: "이 스킬은 자연어 요청을 SQLite 쿼리로 변환하는 방법을 안내합니다. 다양한 데이터베이스 스키마와 질문 유형에 대응할 수 있도록, 테이블 구조와 관계를 이해하고, 적절한 SQL 문장을 생성하는 절차를 포함합니다. 이를 통해 사용자는 자연어로 된 데이터 조회 요청을 효율적이고 정확하게 SQL 쿼리로 전환할 수 있습니다."
---

# 자연어 요청을 SQLite 쿼리로 변환하는 스킬

이 스킬은 자연어로 주어진 데이터 조회 요청을 SQLite 쿼리로 변환하는 절차를 제공합니다. 데이터베이스 스키마와 관계를 이해하고, 적절한 SQL 구문을 구성하는 것이 핵심입니다.

## 절차

1. **요청 분석**: 자연어 요청에서 핵심 정보(조회 대상, 조건, 정렬, 집계 등)를 파악합니다.
2. **테이블 및 컬럼 파악**: 스키마를 참고하여 관련 테이블과 컬럼을 식별합니다.
3. **조건 및 필터링**: 요청에 포함된 조건을 WHERE 절로 변환합니다.
4. **조인 필요 여부 판단**: 여러 테이블에서 정보를 가져와야 하는 경우 JOIN 구문을 사용합니다.
5. **집계 및 그룹화**: 필요한 경우 GROUP BY, COUNT, SUM 등 집계 함수를 적용합니다.
6. **정렬 및 제한**: ORDER BY, LIMIT 등을 활용하여 결과 정렬 및 제한합니다.

## 예제 및 패턴

- **단일 테이블 조회**

  자연어: "학생 중 성별이 여성인 학생 수를 알려줘"

  SQL: ```sql
  SELECT COUNT(*) FROM Student WHERE Sex = 'F';
  ```

- **조건이 있는 다중 테이블 조인**

  자연어: "Smith Hall에 거주하는 여성 학생 수를 알려줘"

  SQL: ```sql
  SELECT COUNT(*) FROM Student
  JOIN Lives_in ON Student.StuID = Lives_in.stuid
  JOIN Dorm ON Lives_in.dormid = Dorm.dormid
  WHERE Dorm.dorm_name = 'Smith Hall' AND Student.Sex = 'F';
  ```

- **집계와 그룹화**

  자연어: "각 클래스별로 선장 수를 알려줘"

  SQL: ```sql
  SELECT Class, COUNT(*) AS CaptainCount FROM captain
  GROUP BY Class
  HAVING COUNT(*) > 2;
  ```

## 사용 조건

- 데이터베이스 스키마와 관계를 이해하고 있어야 합니다.
- 자연어 요청에서 핵심 정보를 명확히 파악할 수 있어야 합니다.
- SQL 문법에 익숙해야 하며, 필요시 조인, 집계, 조건절 등을 적절히 활용할 수 있어야 합니다.

이 스킬은 다양한 데이터베이스 구조와 요청 유형에 적용 가능하며, 자연어를 SQL로 변환하는 기본 틀을 제공합니다.

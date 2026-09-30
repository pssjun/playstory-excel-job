-- 더미 주문 10만 건을 SQL 한 번으로 생성한다.
-- 파이썬 루프로 10만 번 INSERT 하는 대신, Postgres 안에서 generate_series로 한 번에 만든다. (1~2초)

WITH products(pid, product_name, category, price) AS (
    VALUES
        (1,  '비발디파크 스키 리프트권', '스키',     68000),
        (2,  '하이원 스키 강습 2시간',   '스키',     90000),
        (3,  '오션월드 종일권',          '워터파크', 55000),
        (4,  '캐리비안베이 오후권',      '워터파크', 42000),
        (5,  '소노벨 비발디 1박',        '숙박',     159000),
        (6,  '제주 오션뷰 호텔 1박',     '숙박',     210000),
        (7,  '에버랜드 자유이용권',      '테마파크', 62000),
        (8,  '롯데월드 종합이용권',      '테마파크', 59000),
        (9,  '설악 케이블카 왕복',       '레저',     15000),
        (10, '가평 수상레저 패키지',     '레저',     75000)
),
rnd AS (
    -- 행마다 필요한 난수를 미리 뽑아둔다 (random()은 행마다 새로 계산됨)
    SELECT
        g,
        1 + floor(random() * 10)::int AS pid,
        1 + floor(random() * 3)::int  AS qty,
        random()                      AS r_status,
        1 + floor(random() * 10)::int AS last_idx,
        1 + floor(random() * 10)::int AS first_idx,
        random()                      AS r_date
    FROM generate_series(1, 100000) AS g
)
INSERT INTO orders (user_name, product_name, category, amount, status, order_date)
SELECT
    (ARRAY['김','이','박','최','정','강','조','윤','장','임'])[last_idx]
        || (ARRAY['민준','서연','도윤','하은','지호','수아','예준','지우','시우','하린'])[first_idx],
    p.product_name,
    p.category,
    p.price * qty,
    CASE
        WHEN r_status < 0.75 THEN 'confirmed'
        WHEN r_status < 0.90 THEN 'pending'
        ELSE 'cancelled'
    END,
    (now() - r_date * interval '365 days')::timestamp(0)
FROM rnd
JOIN products p USING (pid);

-- 주문 데이터 (과제 스키마 그대로)
CREATE TABLE orders (
    id           SERIAL PRIMARY KEY,
    user_name    VARCHAR(50)  NOT NULL,
    product_name VARCHAR(100) NOT NULL,
    category     VARCHAR(30)  NOT NULL,
    amount       INTEGER      NOT NULL,
    status       VARCHAR(20)  NOT NULL,   -- confirmed / cancelled / pending
    order_date   TIMESTAMP    NOT NULL
);

-- 엑셀 생성 작업 (= 번호표). 이 테이블이 곧 작업 대기열(큐) 역할을 한다.
CREATE TABLE jobs (
    id             SERIAL PRIMARY KEY,
    status         VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending / processing / done / failed
    requested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ,
    file_path      VARCHAR(255),
    total_rows     INTEGER,
    processed_rows INTEGER NOT NULL DEFAULT 0,
    error_message  TEXT,
    CONSTRAINT jobs_status_check CHECK (status IN ('pending', 'processing', 'done', 'failed'))
);

-- 워커가 "가장 오래된 pending 작업"을 찾을 때 쓰는 인덱스
CREATE INDEX idx_jobs_status_id ON jobs (status, id);

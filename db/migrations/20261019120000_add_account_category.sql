-- migrate:up
-- NULL = Uncategorized. Adding a category means a new value here and in
-- models.AccountCategory.
ALTER TABLE accounts ADD COLUMN category TEXT CHECK (
    category IN ('credit_cards', 'bank_accounts', 'investment_accounts', 'tax_liability')
);

-- migrate:down
ALTER TABLE accounts DROP COLUMN category;

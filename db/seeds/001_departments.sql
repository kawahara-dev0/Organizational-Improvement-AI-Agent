-- Seed: sample departments
-- Run after migrations to populate the dropdown in UC-1.

INSERT INTO departments (name) VALUES
    ('Engineering'),
    ('Sales'),
    ('Marketing'),
    ('Human Resources'),
    ('Finance'),
    ('Operations'),
    ('Legal'),
    ('Customer Support')
ON CONFLICT (name) DO NOTHING;

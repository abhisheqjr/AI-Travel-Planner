-- Supabase Schema for Travel Planner

-- Quick Update for Existing Database
-- Run this to add the new summary column if your table already exists:
-- ALTER TABLE public.chat_sessions ADD COLUMN summary TEXT DEFAULT NULL;

-- 1. Users Table (for future login)
CREATE TABLE IF NOT EXISTS public.users (
    id UUID DEFAULT auth.uid() PRIMARY KEY,
    username VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. Chat Sessions Table
CREATE TABLE IF NOT EXISTS public.chat_sessions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES public.users(id) ON DELETE CASCADE, -- Can be null for anonymous sessions before login is built
    title VARCHAR(255) DEFAULT 'New Travel Plan',
    summary TEXT DEFAULT NULL,
    travel_plan JSONB DEFAULT NULL,
    gathered_info JSONB DEFAULT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 3. Messages Table
CREATE TABLE IF NOT EXISTS public.messages (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON public.chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON public.messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON public.messages(created_at);

-- Set up Row Level Security (RLS) - Optional but recommended
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;

-- Simple policies for public access during development (adjust for production)
CREATE POLICY "Allow public read/write users" ON public.users FOR ALL USING (true);
CREATE POLICY "Allow public read/write sessions" ON public.chat_sessions FOR ALL USING (true);
CREATE POLICY "Allow public read/write messages" ON public.messages FOR ALL USING (true);

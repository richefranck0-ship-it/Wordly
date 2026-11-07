-- À exécuter dans Supabase > SQL Editor APRÈS le premier démarrage (les tables sont créées par l'application).
-- L'application se connecte avec le rôle postgres (DATABASE_URL), qui contourne RLS.
-- On active RLS sans politique : l'API publique Supabase (clé anon) ne peut donc rien lire ni écrire.
DO $$ DECLARE t text; BEGIN
  FOR t IN SELECT unnest(ARRAY['settings','categories','sources','articles','push_subscriptions','notifications',
    'ad_requests','campaigns','visits','error_logs','contact_messages']) LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
  END LOOP;
END $$;

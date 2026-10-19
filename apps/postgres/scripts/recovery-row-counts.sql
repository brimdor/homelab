SELECT format('SELECT %L,%L,count(*) FROM ONLY %I.%I',
  encode(sha256(convert_to(n.nspname||'.'||c.relname,'UTF8')),'hex'),
  c.relkind,n.nspname,c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
  AND c.relkind IN ('r','m')
ORDER BY n.nspname,c.relname
\gexec

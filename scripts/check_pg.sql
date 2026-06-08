SELECT pid, usename, application_name, client_addr, datname, state,
       CASE WHEN datname = federation THEN WRONG DB ELSE OK END as flag
FROM pg_stat_activity
WHERE datname != federation_game
ORDER BY pid;
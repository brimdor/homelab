WITH roles AS (
  SELECT jsonb_agg(jsonb_build_array(rolname,rolsuper,rolinherit,rolcreaterole,
    rolcreatedb,rolcanlogin,rolreplication,rolconnlimit,rolvaliduntil::text,
    rolbypassrls,rolconfig) ORDER BY rolname) AS value
  FROM pg_roles WHERE rolname <> 'homelab_restore_admin_20261019'
), members AS (
  SELECT jsonb_agg(jsonb_build_array(r.rolname,m.rolname,g.rolname,
    a.admin_option,a.inherit_option,a.set_option)
    ORDER BY r.rolname,m.rolname,g.rolname) AS value
  FROM pg_auth_members a
  JOIN pg_roles r ON r.oid=a.roleid
  JOIN pg_roles m ON m.oid=a.member
  JOIN pg_roles g ON g.oid=a.grantor
  WHERE r.rolname <> 'homelab_restore_admin_20261019'
    AND m.rolname <> 'homelab_restore_admin_20261019'
    AND NOT (r.rolname LIKE 'pg_%' AND m.rolname LIKE 'pg_%')
), parameters AS (
  SELECT jsonb_agg(jsonb_build_array(parname,paracl::text) ORDER BY parname) AS value
  FROM pg_parameter_acl
)
SELECT encode(sha256(convert_to(jsonb_build_array(roles.value,members.value,
  parameters.value)::text,'UTF8')),'hex') FROM roles,members,parameters;

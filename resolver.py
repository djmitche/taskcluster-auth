import re
import unittest


class BasicResolver(object):

    def __init__(self, roles):
        self.roles = roles

    def satisfies(self, scopes, target):
        for scope in scopes:
            if scope == target:
                return True
            if scope.endswith('*') and target.startswith(scope[:-1]):
                return True
        return False

    def normalizeScopes(self, scopes):
        for scope in scopes:
            if not scope.endswith('*'):
                continue
            # remove any scopes of which this is a prefix
            pfx = scope[:-1]
            scopes = set([scope] + [s for s in scopes if not s.startswith(pfx)])
        return scopes

    def expandScopes(self, scopes):
        scopes = set(scopes)
        while True:
            prev = scopes.copy()
            for role, role_scopes in self.roles.iteritems():
                if role.endswith('*'):
                    pfx = 'assume:{}'.format(role[:-1])
                    if any(s.startswith(pfx) for s in scopes):
                        scopes |= set(role_scopes)
                if self.satisfies(scopes, 'assume:{}'.format(role)):
                    scopes |= set(role_scopes)
            if scopes == prev:
                break

        for scope in scopes:
            if not scope.endswith('*'):
                continue
            # remove any scopes of which this is a prefix
            pfx = scope[:-1]
            scopes = set([scope] + [s for s in scopes if not s.startswith(pfx)])

        return self.normalizeScopes(scopes)


class CommonTests(unittest.TestCase):
    """Tests any resolver should pass; based on existing functionality"""

    resolver = BasicResolver

    def test_identity(self):
        res = self.resolver({})
        self.assertEqual(
            sorted(res.expandScopes(['aa', 'bb'])),
            sorted(['aa', 'bb']))

    def test_expand_simple(self):
        res = self.resolver({
            'role1': ['r1a', 'r1b'],
        })
        self.assertEqual(
            sorted(res.expandScopes(['aa', 'assume:role1'])),
            sorted(['aa', 'assume:role1', 'r1a', 'r1b']))

    def test_expand_star(self):
        res = self.resolver({
            'role1': ['r1a', 'r1b'],
            'role2': ['r2a', 'r2b'],
        })
        self.assertEqual(
            sorted(res.expandScopes(['aa', 'assume:role*'])),
            sorted(['aa', 'assume:role*', 'r1a', 'r1b', 'r2a', 'r2b']))

    def test_expand_role_star(self):
        res = self.resolver({
            'role*': ['rstar'],
            'role2': ['r2a', 'r2b'],
        })
        self.assertEqual(
            sorted(res.expandScopes(['aa', 'assume:role2'])),
            sorted(['aa', 'assume:role2', 'rstar', 'r2a', 'r2b']))

    def test_assume_thing_star(self):
        res = self.resolver({
            'thing-id:*': ['test-scope-1'],
        })
        self.assertEqual(
                sorted(res.expandScopes(['assume:thing-id:test'])),
                sorted(['assume:thing-id:test', 'test-scope-1']))

    def test_assume_can_get_star(self):
        res = self.resolver({
            'thing-id:*': ['*'],
        })
        self.assertEqual(
                sorted(res.expandScopes(['assume:thing-id:test'])),
                sorted(['*']))

    def test_indirect_roles(self):
        res = self.resolver({
            'test-client-1': ['assume:test-role'],
            'test-role': ['special-scope'],
        })
        self.assertEqual(
                sorted(res.expandScopes(['assume:test-client-1'])),
                sorted(['assume:test-client-1', 'assume:test-role', 'special-scope']))

    def test_indirect_roles(self):
        res = self.resolver({
            'test-client-1': ['assume:test-role'],
            'test-role': ['special-scope'],
        })
        self.assertEqual(
                sorted(res.expandScopes(['assume:test-client-1'])),
                sorted(['assume:test-client-1', 'assume:test-role', 'special-scope']))

    def test_many_indirect_roles(self):
        roles = {
            'test-role-{}'.format(n): ['assume:test-role-{}'.format(n+1)]
            for n in range(1, 10)
        }
        roles['test-role-10'] = ['special-scope']
        res = self.resolver(roles)
        self.assertEqual(
                sorted(res.expandScopes(['assume:test-role-1'])),
                sorted(['assume:test-role-{}'.format(n) for n in range(1, 11)]
                       + ['special-scope']))

    def test_cyclic_roles(self):
        res = self.resolver({
            'test-client-1': ['assume:test-role'],
            'test-role': ['special-scope', 'assume:test-client-1'],
        })
        self.assertEqual(
                sorted(res.expandScopes(['assume:test-client-1'])),
                sorted(['assume:test-client-1', 'assume:test-role', 'special-scope']))

    def test_astar_means_assume(self):
        res = self.resolver({
            'test-1': ['a*'],
            'foo': ['bar'],
        })
        self.assertEqual(
                sorted(res.expandScopes(['assume:test-1'])),
                sorted(['a*', 'bar']))

    def test_assumestar_means_assume(self):
        res = self.resolver({
            'test-1': ['assume*'],
            'foo': ['bar'],
        })
        self.assertEqual(
                sorted(res.expandScopes(['assume:test-1'])),
                sorted(['assume*', 'bar']))


class ParameterizedResolver(BasicResolver):

    """Parameterized roles.

    Whatever matches '*' in a roleId is substituted for `<...>` in any of that
    role's scopes.
    """

    def starMatch(self, starMatch, role_scopes):
        pat = re.compile(r'<\.\.\.>')
        scopes = set()
        for rs in role_scopes:
            scopes.add(pat.sub(starMatch, rs))
        return scopes

    def expandScopes(self, scopes):
        scopes = set(scopes)
        iterations = 0
        while True:
            iterations += 1
            if iterations > 100:
                raise RuntimeError('maxium role expansion depth reached')
            prev = scopes.copy()
            for role, role_scopes in self.roles.iteritems():
                if role.endswith('*'):
                    pfx = 'assume:{}'.format(role[:-1])
                    for s in prev:
                        if not s.startswith(pfx):
                            continue
                        scopes.update(self.starMatch(s[len(pfx):], role_scopes))
                else:
                    if self.satisfies(scopes, 'assume:{}'.format(role)):
                        scopes |= set(role_scopes)
            if scopes == prev:
                break

        return self.normalizeScopes(scopes)


class ParameterizedResolverTests(CommonTests):

    resolver = ParameterizedResolver

    def test_parameterized_simple_claim_task(self):
        res = self.resolver({
            'worker-type:*': ['queue:claim-task:<...>'],
        })
        self.assertEqual(
                sorted(res.expandScopes(['assume:worker-type:prov1/wt2'])),
                sorted([
                    'assume:worker-type:prov1/wt2',
                    'queue:claim-task:prov1/wt2',
                ]))
        self.assertEqual(
                sorted(res.expandScopes(['assume:worker-type:prov1/*'])),
                sorted([
                    'assume:worker-type:prov1/*',
                    'queue:claim-task:prov1/*',
                ]))

    def test_parameterized_project_admin(self):
        res = self.resolver({
            'project-admin:*': [
                'auth:create-client:project/<...>/*',
                'assume:project:<...>:*',
                'assume:hook-id:project-<...>/*',
            ],
        })
        self.assertEqual(
                sorted(res.expandScopes(['assume:project-admin:pocket'])),
                sorted([
		    'assume:hook-id:project-pocket/*',
		    'assume:project-admin:pocket',
		    'assume:project:pocket:*',
		    'auth:create-client:project/pocket/*',
                ]))

    def test_parameterized_circular_params(self):
        res = self.resolver({
            'A*': ['assume:B<...>C'],
            'B*': ['assume:A<...>C'],
        })
        self.assertEqual(
                sorted(res.expandScopes(['assume:A'])),
                sorted(['assume*', 'bar']))

    def test_parameterized_star_in_replacement(self):
        res = self.resolver({
            'A*': ['assume:B<...>C'],
        })
        self.assertEqual(
                sorted(res.expandScopes(['assume:Abc*'])),
                sorted(['assume:Abc*', 'assume:Bbc*C']))


class ParameterizedResolverWithStarExpansion(ParameterizedResolver):

    """Like ParameterizedResolver, but if a `*` is substitued in `<...>`, everything
    after that `*` is discarded.
    """

    def starMatch(self, starMatch, role_scopes):
        if starMatch.endswith('*'):
            pat = re.compile(r'<\.\.\.>.*')  # * in starMatch consumes everything after <...>
        else:
            pat = re.compile(r'<\.\.\.>')
        scopes = set()
        for rs in role_scopes:
            scopes.add(pat.sub(starMatch, rs))
        return scopes


class ParameterizedResolverWithStarExpansionTests(ParameterizedResolverTests):

    resolver = ParameterizedResolverWithStarExpansion


    def test_parameterized_scope_escalation(self):
        res = self.resolver({
            'project:taskcluster:docs-upload:*': [
                'auth:aws-s3:read-write:tc-metadata-<...>/docs',
            ],
        })
        self.assertEqual(
                sorted(res.expandScopes(['assume:project:taskcluster:docs-upload:queue'])),
                sorted([
                    'assume:project:taskcluster:docs-upload:queue',
                    'auth:aws-s3:read-write:tc-metadata-queue/docs', # looks good..
                ]))

        self.assertEqual(
                sorted(res.expandScopes(['assume:project:taskcluster:docs-upload:*'])),
                sorted([
                    'assume:project:taskcluster:docs-upload:*',
                    'auth:aws-s3:read-write:tc-metadata-*', # SURPRISE!
                ]))

    def test_parameterized_star_in_replacement(self): # overrides parent class
        res = self.resolver({
            'A*': ['assume:B<...>C'],
        })
        self.assertEqual(
                sorted(res.expandScopes(['assume:Abc*'])),
                sorted(['assume:Abc*', 'assume:Bbc*']))

unittest.main()

from manniu_auth.models import AuthScope


def user_scopes(user):
    codes = AuthScope.objects.filter(
        role_scopes__role__user_roles__user=user,
    ).values_list('code', flat=True)
    return sorted(set(codes))

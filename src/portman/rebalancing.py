from decimal import Decimal

def plan_rebalancing(current, targets, cash=0, tolerance_pct=1, minimum_order=100, fee=0, buys_only=True):
    """Create group-level orders. Amounts are security values; fees consume cash separately."""
    current={k:Decimal(str(v)) for k,v in current.items()};targets={k:Decimal(str(v)) for k,v in targets.items()}
    cash=Decimal(str(cash));tol=Decimal(str(tolerance_pct));minimum=Decimal(str(minimum_order));fee=Decimal(str(fee));total=sum(current.values(),Decimal(0));projected_total=total+cash
    raw={};result=[]
    for group,target in targets.items():
        now=current.get(group,Decimal(0));weight=now/total*100 if total else Decimal(0);gap=projected_total*target/100-now
        raw[group]=Decimal(0) if abs(weight-target)<=tol else gap
    # Only executable sales may finance buys; reserve fees on both sides.
    actions = {group: (value if not buys_only and value < 0
                      and -value >= minimum and -value > fee else Decimal(0))
               for group, value in raw.items()}
    sales = -sum(actions.values(), Decimal(0))
    sale_fees = fee * sum(value < 0 for value in actions.values())
    candidates = {group: value for group, value in raw.items()
                  if value > 0 and value >= minimum}
    desired = sum(candidates.values(), Decimal(0))
    available = max(cash + sales - sale_fees - fee * len(candidates), Decimal(0))
    scale = min(Decimal(1), available / desired) if desired else Decimal(0)
    for group, value in candidates.items():
        action = value * scale
        if action >= minimum:
            actions[group] = action
    post = dict(current)
    for group, action in actions.items():
        post[group] = post.get(group, Decimal(0)) + action
    post_total=sum(post.values(),Decimal(0))
    for group,target in targets.items():
        now=current.get(group,Decimal(0));action=post.get(group,now)-now
        result.append({'group':group,'current':now,'current_pct':now/total*100 if total else Decimal(0),'target_pct':target,
          'target_value':projected_total*target/100,'action':action,'fee':fee if action else Decimal(0),'after':post.get(group,now),
          'after_pct':post.get(group,now)/post_total*100 if post_total else Decimal(0),'within_tolerance':raw[group]==0})
    return {'rows':result,'target_sum':sum(targets.values(),Decimal(0)),'cash_used':sum((max(r['action'],Decimal(0))+r['fee'] for r in result),Decimal(0)),
            'sales':sum((-min(r['action'],Decimal(0)) for r in result),Decimal(0)),'post_total':post_total}

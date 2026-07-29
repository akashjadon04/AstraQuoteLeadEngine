from typing import List, Dict, Tuple, Any

def check_quota(leads: List[Dict[str, Any]], target: int = 100) -> Tuple[bool, int]:
    """
    Check if we have enough leads.
    """
    current_count = len(leads)
    return current_count >= target, current_count

def select_top(leads: List[Dict[str, Any]], count: int = 100) -> List[Dict[str, Any]]:
    """
    Select top leads by data completeness score.
    (has_phone=30pts, has_website=20pts, has_email=20pts, in_target_niche=30pts)
    """
    def score_lead(lead: Dict[str, Any]) -> int:
        score = 0
        if lead.get('phone'): score += 30
        if lead.get('website') and not 'duckduckgo' in lead.get('website', ''): score += 20
        if lead.get('email'): score += 20
        if lead.get('niche'): score += 30
        return score
        
    scored_leads = [(score_lead(l), l) for l in leads]
    scored_leads.sort(key=lambda x: x[0], reverse=True)
    
    return [l for s, l in scored_leads[:count]]

from medigap_engine.experience.decomp import differential, fit_main_effects


def test_isolates_confounded_effect():
    # Construct premiums where gender is exactly +15% but males skew to a cheaper plan,
    # so the raw marginal understates the gender effect. The fit must recover +15%.
    base = {"A": 1000.0, "B": 800.0}      # plan A dearer than plan B
    gfac = {"M": 1.15, "F": 1.0}
    obs = []
    # females mostly plan A (dear); males mostly plan B (cheap) -> raw marginal confounded
    obs.append((("F", "A"), base["A"] * gfac["F"], 90))
    obs.append((("F", "B"), base["B"] * gfac["F"], 10))
    obs.append((("M", "A"), base["A"] * gfac["M"], 10))
    obs.append((("M", "B"), base["B"] * gfac["M"], 90))
    fit = fit_main_effects(obs, n_dims=2)
    assert abs(differential(fit["factors"], 0, "M", "F") - 0.15) < 1e-6


def test_empty_observations():
    fit = fit_main_effects([], n_dims=3)
    assert fit["factors"] == [{}, {}, {}]

// Constants for turning tonnes into everyday terms on the dashboard.
// Keep every number sourced; tests check each one has a source URL.
window.CG_IMPACT = {
  carTonnesPerYear: 4.6, // typical passenger vehicle, tCO2 per year
  carSource: "https://www.epa.gov/greenvehicles/greenhouse-gas-emissions-typical-passenger-vehicle",
  // Conservative: these are junk credits, so price them like low-rated ones.
  priceUsdPerTonne: 3.5, // reported 2024 average for CCC-B rated voluntary credits (secondary source)
  priceNote: "assumed price of low-rated credits; high-rated credits averaged about $15/t in 2024",
  priceSource: "https://carboncredits.com/",
};

"""
Data Fetching Agent
Asynchronously fetches price data, volume, on-chain metrics, and volatility data.
Normalizes all data into a consistent format and implements basic caching.
"""

from typing import Any, Dict, Optional, List
from datetime import datetime, timedelta
import logging

from utils.multi_provider_client import fetch_simple_price

from .base_agent import BaseAgent, AgentStatus


class DataFetchingAgent(BaseAgent):
    """
    Data Fetching Agent: Retrieves market and on-chain data from public APIs.
    
    Responsibilities:
    - Fetch price data from multiple sources
    - Fetch volume and volatility metrics
    - Fetch on-chain metrics (Solana-focused)
    - Normalize data format
    - Implement caching to reduce API calls
    - Handle API errors gracefully
    
    APIs Used:
    - Binance Public (free, no auth required)
    - Kraken Public (free, no auth required)
    - CoinGecko (fallback, free, no auth required)
    - DeFiLlama (free, no auth required)
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the data fetching agent."""
        super().__init__("DataFetchingAgent", config)
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.cache_timeout = 300  # 5 minutes
        self.defilamma_base_url = "https://api.llama.fi"
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid."""
        if cache_key not in self.cache:
            return False
        
        cached_time = self.cache[cache_key].get('timestamp')
        if not cached_time:
            return False
        
        age = (datetime.utcnow() - cached_time).total_seconds()
        return age < self.cache_timeout
    
    def _get_coingecko_id(self, trading_pair: str) -> Optional[str]:
        """Map trading pair like 'SOL/USDT' or 'SOL' to CoinGecko ID."""
        mapping = {
            'SOL': 'solana',
            'BTC': 'bitcoin',
            'ETH': 'ethereum',
            'USDC': 'usd-coin',
            'USDT': 'tether',
            'RAY': 'raydium',
            'COPE': 'cope',
            'ORCA': 'orca',
        }
        try:
            base_asset = trading_pair.split('/', 1)[0].upper()
            coingecko_id = mapping.get(base_asset)
            if not coingecko_id:
                self.logger.warning(
                    f"No CoinGecko ID found for base asset '{base_asset}' from pair '{trading_pair}'"
                )
            return coingecko_id
        except (AttributeError, IndexError):
            self.logger.error(
                f"Could not parse trading pair format: '{trading_pair}'. Expected format like 'BASE/QUOTE'."
            )
            return None
    
    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch market data for specified symbols.
        
        Args:
            input_data: Must contain 'symbols' list (e.g., ['SOL/USDT', 'BTC/USDT'])
            
        Returns:
            Message with normalized market data
        """
        self.log_execution_start("fetch_market_data")
        
        try:
            symbols = input_data.get('symbols', [])
            if not symbols:
                raise ValueError("No symbols provided")
            
            market_data = {}
            
            for pair in symbols:
                self.logger.info(f"Fetching data for {pair}")
                
                # Parse pair
                parts = pair.split('/')
                if len(parts) != 2:
                    self.logger.warning(f"Invalid pair format: {pair}")
                    continue
                
                base_symbol, quote_symbol = parts
                coingecko_id = self._get_coingecko_id(base_symbol)
                
                if not coingecko_id:
                    self.logger.warning(f"Unknown symbol: {base_symbol}")
                    continue
                
                # Normalize quote currency for CoinGecko (use USD for USDT)
                vs_currency = quote_symbol.lower()
                if vs_currency in {"usdt", "usd"}:
                    vs_currency = "usd"

                # Try cache first
                cache_key = f"{coingecko_id}_{vs_currency}"
                if self._is_cache_valid(cache_key):
                    self.logger.info(f"Using cached data for {pair}")
                    market_data[pair] = self.cache[cache_key]['data']
                    continue
                
                # Fetch from API
                price_data = self._fetch_price_data(coingecko_id, vs_currency)
                if price_data:
                    # Normalize data
                    normalized = self._normalize_data(pair, price_data)
                    market_data[pair] = normalized
                    
                    # Cache it
                    self.cache[cache_key] = {
                        'data': normalized,
                        'timestamp': datetime.utcnow()
                    }
                    self.logger.info(f"✓ Fetched {pair}: ${normalized['current_price']:.4f}")
            
            if not market_data:
                raise ValueError("Failed to fetch data for any symbol")
            
            self.log_execution_end("fetch_market_data", success=True)
            
            return self.create_message(
                action='fetch_market_data',
                success=True,
                data={
                    'market_data': market_data,
                    'symbols_count': len(market_data),
                    'cache_size': len(self.cache),
                    'timestamp': datetime.utcnow().isoformat()
                }
            )
        
        except Exception as e:
            error_msg = f"Data fetching error: {str(e)}"
            self.set_status(AgentStatus.ERROR, error_msg)
            self.log_execution_end("fetch_market_data", success=False)
            return self.create_message(
                action='fetch_market_data',
                success=False,
                error=error_msg
            )
    
    def _fetch_price_data(self, coingecko_id: str, vs_currency: str = 'usd') -> Optional[Dict[str, Any]]:
        """
        Fetch price data from CoinGecko API.
        
        Args:
            coingecko_id: CoinGecko ID for the token
            vs_currency: Target currency (default: USD)
            
        Returns:
            Price data dictionary or None on error
        """
        try:
            data = fetch_simple_price(ids=[coingecko_id], vs_currency=vs_currency)
            if coingecko_id in data:
                return data[coingecko_id]
            return None
        except Exception as e:
            self.logger.error(f"CoinGecko API error: {str(e)}")
            return None
    
    def _normalize_data(self, pair: str, price_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize API data into standard format.
        
        Args:
            pair: Trading pair (e.g., 'SOL/USDT')
            price_data: Raw price data from API
            
        Returns:
            Normalized data dictionary
        """
        currency = 'usd'  # CoinGecko returns USD by default
        
        return {
            'pair': pair,
            'current_price': price_data.get(currency, 0),
            'market_cap': price_data.get('market_cap', {}).get(currency, 0),
            'volume_24h': price_data.get('usd_24h_vol', 0),
            'price_change_24h': price_data.get('usd_24h_change', 0),
            'price_change_24h_pct': price_data.get('usd_24h_change', 0),
            'last_updated': datetime.utcnow().isoformat(),
            'currency': currency.upper()
        }
    
    def clear_cache(self) -> None:
        """Clear all cached data."""
        self.cache.clear()
        self.logger.info("Cache cleared")
    
    def get_cache_status(self) -> Dict[str, Any]:
        """Get cache statistics."""
        valid_entries = sum(1 for key in self.cache if self._is_cache_valid(key))
        return {
            'total_entries': len(self.cache),
            'valid_entries': valid_entries,
            'timeout_seconds': self.cache_timeout
        }

# liveserverplus_lib/connection_manager.py
import threading
import time
import collections
from .logging import debug, info, warning, error

class ConnectionManager:
    """Manages active connections to prevent resource exhaustion"""
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        """Get or create singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        """Initialize the connection manager"""
        self.active_connections = set()
        self.connection_lock = threading.Lock()
        self.max_connections = 100
        self.requests_per_client = collections.defaultdict(int)
        self.last_cleanup = time.time()
        self.cleanup_interval = 60  # Cleanup old data every minute
        
    def configure(self, settings):
        """
        Configure from settings
        
        Args:
            settings: Server settings object
        """
        if hasattr(settings, '_settings'):
            conn_settings = settings._settings.get('connections', {})
            self.max_connections = conn_settings.get('max_concurrent', 100)
            
    def add_connection(self, conn, addr):
        """
        Add a new connection if below maximum
        
        Args:
            conn: Socket connection
            addr: Client address tuple
            
        Returns:
            bool: True if connection was added, False if rejected
        """
        with self.connection_lock:
            # Clean up old data occasionally
            current_time = time.time()
            if current_time - self.last_cleanup > self.cleanup_interval:
                self._cleanup()
                self.last_cleanup = current_time
                
            # Check if we're at the connection limit
            if len(self.active_connections) >= self.max_connections:
                warning(f"Connection limit reached ({self.max_connections}), rejecting connection from {addr}")
                return False
                
            # Record the connection
            self.active_connections.add(conn)
            self.requests_per_client[addr[0]] += 1
            
            debug(f"New connection from {addr}, total active: {len(self.active_connections)}")
            return True
            
    def remove_connection(self, conn):
        """
        Remove a connection from the active set
        
        Args:
            conn: Socket connection
        """
        with self.connection_lock:
            if conn in self.active_connections:
                self.active_connections.remove(conn)
                
    def _cleanup(self):
        """Clean up stale connections and request data"""
        # Clear request counts older than 1 hour
        current_time = time.time()
        stale_entries = []
        
        for client_ip in self.requests_per_client:
            if current_time - self.last_cleanup > 3600:  # 1 hour
                stale_entries.append(client_ip)
                
        for client_ip in stale_entries:
            del self.requests_per_client[client_ip]
            
        debug(f"Cleaned up connection data, active connections: {len(self.active_connections)}")
    
    def get_stats(self):
        """
        Get statistics about connections
        
        Returns:
            dict: Connection statistics
        """
        with self.connection_lock:
            active_count = len(self.active_connections)
            unique_clients = len(self.requests_per_client)
            
            # Get top clients by request count
            top_clients = sorted(
                self.requests_per_client.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:5]
            
            return {
                'active_connections': active_count,
                'max_connections': self.max_connections,
                'unique_clients': unique_clients,
                'top_clients': [{'ip': ip, 'requests': count} for ip, count in top_clients]
            }
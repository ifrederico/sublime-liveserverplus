# liveserverplus_lib/connection_manager.py
import threading
import time
import collections
from .logging import info, error
from .http_utils import HTTPResponse
from .error_pages import ErrorPages


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
        self.max_threads = 10  # Simplified to just max_threads
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
            # Simplified: just get max_threads
            self.max_threads = settings._settings.get('max_threads', 10)
            
    def add_connection(self, conn, addr):
        """
        Add a new connection if below maximum. Send 503 if server is busy.
        
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
                
            # Check if we're at the connection limit (using max_threads as limit)
            if len(self.active_connections) >= self.max_threads:
                error(f"Connection limit reached ({self.max_threads}), rejecting connection from {addr}")
                
                # Send 503 Service Unavailable response using ErrorPages
                try:
                    error_html = ErrorPages.get_503_page(retry_after=5)
                    
                    response = HTTPResponse(503)
                    response.set_header('Content-Type', 'text/html; charset=utf-8')
                    response.set_header('Retry-After', '5')
                    response.set_body(error_html)
                    response.send(conn)
                except Exception as e:
                    error(f"Failed to send 503 response: {e}")
                
                return False
                
            # Record the connection
            self.active_connections.add(conn)
            self.requests_per_client[addr[0]] += 1
            
            info(f"New connection from {addr}, total active: {len(self.active_connections)}")
            return True
            
    def remove_connection(self, conn):
        """
        Remove a connection from the active set
        
        Args:
            conn: Socket connection
        """
        with self.connection_lock:
            self.active_connections.discard(conn)
            info(f"Connection removed, total active: {len(self.active_connections)}")
                
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
            
        info(f"Cleaned up connection data, active connections: {len(self.active_connections)}")
    
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
                'max_threads': self.max_threads,
                'unique_clients': unique_clients,
                'top_clients': [{'ip': ip, 'requests': count} for ip, count in top_clients]
            }
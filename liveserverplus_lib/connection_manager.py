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
    def getInstance(cls):
        """Get or create singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        """Initialize the connection manager"""
        self.active_connections = set()
        self.connection_lock = threading.Lock()
        self.max_threads = 10
        self.requests_per_client = collections.defaultdict(int)
        self.last_request_time = {}  # Track last request time per client
        self.last_cleanup = time.time()
        self.cleanup_interval = 60  # Cleanup old data every minute
        

    def configure(self, settings):
        """
        Configure from settings
        
        Args:
            settings: Server settings object
        """
        self.max_threads = max(1, int(getattr(settings, 'maxThreads', 10)))
            
    def addConnection(self, conn, addr):
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
                
            # Check if we're at the connection limit
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
            self.last_request_time[addr[0]] = current_time  # Track time of this request
            
            info(f"New connection from {addr}, total active: {len(self.active_connections)}")
            return True
            
    def removeConnection(self, conn):
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
        
        # Check each client's last request time
        for client_ip, last_time in list(self.last_request_time.items()):
            if current_time - last_time > 3600:  # 1 hour since last request
                stale_entries.append(client_ip)
                
        for client_ip in stale_entries:
            del self.requests_per_client[client_ip]
            del self.last_request_time[client_ip]
            
        info(f"Cleaned up connection data for {len(stale_entries)} stale clients, active connections: {len(self.active_connections)}")
    
    def getStats(self):
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

    # Backwards compatibility methods
    @classmethod
    def get_instance(cls):
        return cls.getInstance()

    def add_connection(self, conn, addr):
        return self.addConnection(conn, addr)

    def remove_connection(self, conn):
        return self.removeConnection(conn)

    def get_stats(self):
        return self.getStats()

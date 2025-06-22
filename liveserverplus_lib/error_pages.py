# error_pages.py
"""Error pages handler module with centralized HTML generation"""
import os
from http.client import responses
from .directory_listing import DirectoryListing
from .text_utils import find_similar_files


class ErrorPages:
    """Handles custom error pages with consistent styling."""
    
    # Common CSS for all error pages
    ERROR_PAGE_CSS = """
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
            text-align: center;
            padding: 50px;
            margin: 0;
            background: #f5f5f5;
        }
        .container {
            max-width: 600px;
            margin: 0 auto;
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            color: #e74c3c;
            margin-bottom: 10px;
            font-size: 48px;
        }
        h2 {
            color: #333;
            font-weight: normal;
            margin-bottom: 30px;
        }
        p {
            color: #666;
            line-height: 1.6;
        }
        code {
            background: #f0f0f0;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: monospace;
        }
        .suggestion {
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
            text-align: left;
        }
        .suggestion ul {
            margin: 10px 0 0 20px;
            padding: 0;
        }
        .suggestion li {
            margin: 5px 0;
        }
        a {
            color: #3498db;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        .back-link {
            margin-top: 30px;
        }
        small {
            color: #999;
        }
    """
    
    @staticmethod
    def get_error_page(status_code, message=None, details=None, suggestions=None):
        """
        Generate a generic error page for any status code.
        
        Args:
            status_code (int): HTTP status code
            message (str): Error message (defaults to standard HTTP message)
            details (str): Additional details about the error
            suggestions (str): HTML content for suggestions
            
        Returns:
            str: Complete HTML error page
        """
        if message is None:
            message = responses.get(status_code, "Unknown Error")
            
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{status_code} {message}</title>
    <style>{ErrorPages.ERROR_PAGE_CSS}</style>
</head>
<body>
    <div class="container">
        <h1>{status_code}</h1>
        <h2>{message}</h2>
        {f'<p>{details}</p>' if details else ''}
        {suggestions or ''}
        <div class="back-link">
            <a href="/">&larr; Back to home</a>
        </div>
    </div>
</body>
</html>"""
    
    @staticmethod
    def get_404_page(path, folders, settings=None):
        """
        Generate a 404 page or a directory listing if path is a folder.
        
        Args:
            path: The requested URL path (e.g. "/somefile").
            folders: The server's list of project folders.
            settings: (Optional) A ServerSettings instance, used by DirectoryListing.
            
        Returns:
            str: A UTF-8 HTML string
        """
        # Check if path is actually a directory
        for folder in folders:
            full_path = os.path.join(folder, path.lstrip("/"))
            if os.path.isdir(full_path):
                directory_lister = DirectoryListing(settings=settings)
                listing_bytes = directory_lister.generate_listing(
                    dir_path=full_path,
                    url_path=path,
                    root_path=folder
                )
                return listing_bytes.decode("utf-8", errors="replace")
        
        # Generate suggestions
        suggestions_html = ErrorPages._generate_suggestions(path, folders)
        
        # Use the generic error page generator
        return ErrorPages.get_error_page(
            status_code=404,
            message="Page Not Found",
            details=f'The requested URL <code>{path}</code> was not found on this server.',
            suggestions=suggestions_html
        )
    
    @staticmethod
    def get_503_page(retry_after=5):
        """
        Generate a 503 Service Unavailable page.
        
        Args:
            retry_after (int): Seconds until client should retry
            
        Returns:
            str: Complete HTML error page
        """
        return ErrorPages.get_error_page(
            status_code=503,
            message="Service Unavailable",
            details=f"""The server is currently unable to handle your request due to temporary overload.
                       Please try again in {retry_after} seconds.""",
            suggestions='<p><small>Maximum concurrent connections reached</small></p>'
        )
    
    @staticmethod
    def get_500_page(error_id=None):
        """
        Generate a 500 Internal Server Error page.
        
        Args:
            error_id (str): Optional error ID for tracking
            
        Returns:
            str: Complete HTML error page
        """
        details = "The server encountered an internal error and was unable to complete your request."
        if error_id:
            details += f"<br><br><small>Error ID: {error_id}</small>"
            
        return ErrorPages.get_error_page(
            status_code=500,
            message="Internal Server Error",
            details=details
        )
    
    @staticmethod
    def get_400_page(reason=None):
        """
        Generate a 400 Bad Request page.
        
        Args:
            reason (str): Optional reason for the bad request
            
        Returns:
            str: Complete HTML error page
        """
        details = reason or "The server cannot process your request due to invalid syntax."
        
        return ErrorPages.get_error_page(
            status_code=400,
            message="Bad Request",
            details=details
        )

    @staticmethod
    def _generate_suggestions(path, folders):
        """
        Generate "Did you mean:" file suggestions using text_utils.
        
        Returns:
            str: HTML snippet with suggestions or empty string
        """
        # Use text_utils function for finding similar files
        suggestions = find_similar_files(path, folders, threshold=0.5, max_results=5)
        
        if not suggestions:
            return ""
        
        # Generate suggestion HTML
        items_html = "".join(
            f'<li><a href="/{file_path}">{file_path}</a></li>'
            for file_path, _ in suggestions
        )

        return f"""<div class="suggestion">
    <strong>Did you mean:</strong>
    <ul>{items_html}</ul>
</div>"""
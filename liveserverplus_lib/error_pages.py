# error_pages.py
"""Error pages handler module"""
import os
from .directory_listing import DirectoryListing

class ErrorPages:
    """Handles custom error pages"""
    
    @staticmethod
    def get_404_page(path, folders):
        """Generate custom 404 page with directory listing if applicable"""
        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>404 - Not Found</title>
            <style>
                {DirectoryListing.get_base_styles()}
                h1 {{ color: #e74c3c; margin-bottom: 10px; }}
                .directory {{ 
                    background: #f8f9fa; 
                    border-radius: 4px; 
                    padding: 20px; 
                    margin: 20px 0; 
                }}
                .suggestion {{ 
                    background: #fff3cd; 
                    padding: 10px; 
                    border-radius: 4px; 
                    margin: 10px 0; 
                }}
            </style>
        </head>
        <body>
            <h1>404 - Page Not Found</h1>
            <p>The requested URL <code>{path}</code> was not found on this server.</p>
        """
        
        # Check if path is a directory
        for folder in folders:
            full_path = os.path.join(folder, path.lstrip('/'))
            if os.path.isdir(full_path):
                # Use the DirectoryListing class for consistent listing
                items = DirectoryListing.generate_items_list(full_path)
                html += f"""
                <div class="directory">
                    <h2>Directory listing for {path}</h2>
                    {DirectoryListing.generate_table_html(items, path)}
                </div>
                """
                break
        else:
            # Add suggestions
            html += ErrorPages._generate_suggestions(path, folders)
        
        html += """
            <p><a href="/">&larr; Back to home</a></p>
        </body>
        </html>
        """
        
        return html
    
    @staticmethod
    def _generate_suggestions(path, folders):
        """Generate file suggestions based on similarity"""
        suggestions = []
        search_name = os.path.basename(path)
        
        for folder in folders:
            for root, _, files in os.walk(folder):
                for file in files:
                    if ErrorPages._similar(search_name.lower(), file.lower()) > 0.5:
                        rel_path = os.path.relpath(os.path.join(root, file), folder)
                        suggestions.append(rel_path.replace('\\', '/'))
        
        if suggestions:
            html = """
            <div class="suggestion">
                <strong>Did you mean:</strong>
                <ul>
            """
            for suggestion in suggestions[:5]:  # Show top 5 suggestions
                html += f'<li><a href="/{suggestion}">{suggestion}</a></li>'
            html += "</ul></div>"
            return html
        return ""
    
    @staticmethod
    def _similar(a, b):
        """Calculate string similarity ratio"""
        if len(a) > len(b):
            a, b = b, a
        distances = range(len(a) + 1)
        for i2, c2 in enumerate(b):
            distances_ = [i2+1]
            for i1, c1 in enumerate(a):
                if c1 == c2:
                    distances_.append(distances[i1])
                else:
                    distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
            distances = distances_
        return 1 - (distances[-1] / max(len(a), len(b)))
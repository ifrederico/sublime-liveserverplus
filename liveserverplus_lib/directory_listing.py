"""Directory listing module"""
import os
from datetime import datetime
from typing import Dict, List, Any

class DirectoryListing:
    """Handles directory listing pages"""

    # File type icons mapping
    ICONS = {
        # HTML/Web
        '.html': '📄',
        '.htm': '📄',
        '.css': '🎨',
        '.js': '📜',
        '.json': '📝',
        '.xml': '📋',
        
        # Images
        '.jpg': '🖼️',
        '.jpeg': '🖼️',
        '.png': '🖼️',
        '.gif': '🖼️',
        '.svg': '🖼️',
        '.ico': '🖼️',
        
        # Documents
        '.pdf': '📕',
        '.doc': '📘',
        '.docx': '📘',
        '.txt': '📝',
        '.md': '📝',
        
        # Code
        '.py': '🐍',
        '.jsx': '📜',
        '.ts': '📜',
        '.tsx': '📜',
        
        # Archives
        '.zip': '📦',
        '.rar': '📦',
        '.7z': '📦',
        
        # Media
        '.mp3': '🎵',
        '.wav': '🎵',
        '.mp4': '🎬',
        '.avi': '🎬',
        '.mov': '🎬'
    }

    @staticmethod
    def get_base_styles() -> str:
        """Get common CSS styles for directory listings"""
        return """
            body { 
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
                line-height: 1.6;
                max-width: 1200px;
                margin: 20px auto;
                padding: 0 20px;
                color: #333;
            }
            h1 { color: #2c3e50; margin-bottom: 20px; }
            .directory-path {
                background: #f8f9fa;
                padding: 10px;
                border-radius: 4px;
                margin-bottom: 20px;
                font-family: monospace;
            }
            table { 
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }
            th, td { 
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #eee;
            }
            th { 
                background: #f8f9fa;
                color: #666;
                font-weight: 500;
            }
            td { vertical-align: middle; }
            a { 
                color: #3498db;
                text-decoration: none;
                display: flex;
                align-items: center;
                gap: 8px;
            }
            a:hover { color: #2980b9; }
            .size { width: 100px; text-align: right; }
            .modified { width: 200px; }
            .icon { font-size: 1.2em; }
            tr:hover { background: #f8f9fa; }
            .parent-link {
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 8px 16px;
                background: #eee;
                border-radius: 4px;
                margin-bottom: 20px;
            }"""

    @staticmethod
    def get_file_info(path: str, entry: os.DirEntry = None) -> Dict[str, Any]:
        """Get standardized file information"""
        try:
            if entry:
                is_dir = entry.is_dir()
                name = entry.name
                stat_info = entry.stat()
            else:
                is_dir = os.path.isdir(path)
                name = os.path.basename(path)
                stat_info = os.stat(path)

            if is_dir:
                return {
                    'name': name,
                    'icon': "📁",
                    'type': "directory",
                    'size': "-",
                    'modified': datetime.fromtimestamp(stat_info.st_mtime)
                }
            else:
                ext = os.path.splitext(name)[1].lower()
                return {
                    'name': name,
                    'icon': DirectoryListing.ICONS.get(ext, '📄'),
                    'type': "file",
                    'size': DirectoryListing._format_size(stat_info.st_size),
                    'modified': datetime.fromtimestamp(stat_info.st_mtime)
                }
        except Exception as e:
            print(f"Error getting file info for {path}: {e}")
            return None

    @staticmethod
    def generate_items_list(dir_path: str, include_hidden: bool = False) -> List[Dict[str, Any]]:
        """Generate list of directory items with consistent formatting"""
        items = []
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if not include_hidden and entry.name.startswith('.'):
                        continue
                    file_info = DirectoryListing.get_file_info(entry.path, entry)
                    if file_info:
                        items.append(file_info)
            
            # Sort: directories first, then files, all alphabetically
            return sorted(items, key=lambda x: (x['type'] != 'directory', x['name'].lower()))
        except Exception as e:
            print(f"Error generating items list for {dir_path}: {e}")
            return []

    @staticmethod
    def generate_table_html(items: List[Dict[str, Any]], url_path: str) -> str:
        """Generate HTML table for directory items"""
        html = """
            <table>
                <thead>
                    <tr>
                        <th colspan="2">Name</th>
                        <th class="size">Size</th>
                        <th class="modified">Last Modified</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for item in items:
            item_path = os.path.join(url_path, item['name']).replace('\\', '/')
            if item['type'] == 'directory':
                item_path += '/'
            
            html += f"""
                <tr>
                    <td style="width: 40px"><div class="icon">{item['icon']}</div></td>
                    <td><a href="{item_path}">{item['name']}</a></td>
                    <td class="size">{item['size']}</td>
                    <td class="modified">{item['modified'].strftime('%Y-%m-%d %H:%M')}</td>
                </tr>
            """
        
        html += """
                </tbody>
            </table>
        """
        return html

    @staticmethod
    def generate_listing(dir_path: str, url_path: str, root_path: str) -> bytes:
        """Generate complete directory listing page"""
        try:
            items = DirectoryListing.generate_items_list(dir_path)
            
            html = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Directory: {url_path}</title>
                <style>
                    {DirectoryListing.get_base_styles()}
                </style>
            </head>
            <body>
                <h1>Directory Listing</h1>
                <div class="directory-path">{url_path}</div>
            """
            
            # Add parent directory link if not at root
            if url_path != '/':
                parent = os.path.dirname(url_path.rstrip('/'))
                html += f'<a href="{parent or "/"}" class="parent-link">📁 Parent Directory</a>'
            
            html += DirectoryListing.generate_table_html(items, url_path)
            
            html += """
            </body>
            </html>
            """
            
            return html.encode('utf-8')
            
        except Exception as e:
            return f"<p>Error reading directory: {e}</p>".encode('utf-8')

    @staticmethod
    def _format_size(size: int) -> str:
        """Format file size in human readable format"""
        try:
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024:
                    return f"{size:.1f} {unit}"
                size /= 1024
            return f"{size:.1f} TB"
        except Exception as e:
            print(f"Error formatting size: {e}")
            return "-"
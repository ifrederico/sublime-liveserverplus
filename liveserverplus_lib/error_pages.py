# error_pages.py
"""Error pages handler module"""
import os
from .directory_listing import DirectoryListing

class ErrorPages:
    """Handles custom error pages."""
    
    @staticmethod
    def get_404_page(path, folders, settings=None):
        """
        Generate a 404 page or a directory listing if `path` is a folder.
        
        :param path: The requested URL path (e.g. "/somefile").
        :param folders: The server’s list of project folders.
        :param settings: (Optional) A ServerSettings instance, used by DirectoryListing.
        :return: A UTF-8 HTML string (the entire HTML doc).
        """
        # 1) If path is actually a directory, serve the directory listing’s full doc
        for folder in folders:
            full_path = os.path.join(folder, path.lstrip("/"))
            if os.path.isdir(full_path):
                directory_lister = DirectoryListing(settings=settings)
                listing_bytes = directory_lister.generate_listing(
                    dir_path=full_path,
                    url_path=path,
                    root_path=folder
                )
                # Convert from bytes to string for consistency
                return listing_bytes.decode("utf-8", errors="replace")
        
        # 2) If not a directory, build a standalone 404 HTML doc
        #    (ensuring we do not embed the directory listing’s <html> again).
        suggestions_html = ErrorPages._generate_suggestions(path, folders)
        return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>404 Not Found</title>
    <style>
        /* Simple CSS for the 404 page */
        h1 {{
            color: #e74c3c;
            margin-bottom: 10px;
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
    {suggestions_html}
    <p><a href="/">&larr; Back to home</a></p>
</body>
</html>
"""

    @staticmethod
    def _generate_suggestions(path, folders):
        """
        Generate "Did you mean:" file suggestions based on naive string similarity.
        Return an empty string if no suggestions are found.
        """
        suggestions = []
        search_name = os.path.basename(path)

        for folder in folders:
            for root, _, files in os.walk(folder):
                for filename in files:
                    # If it's > 0.5 similarity, consider it "close"
                    if ErrorPages._similar(search_name.lower(), filename.lower()) > 0.5:
                        rel_path = os.path.relpath(os.path.join(root, filename), folder)
                        suggestions.append(rel_path.replace("\\", "/"))

        if not suggestions:
            return ""
        
        # Show up to 5 suggestions
        items_html = "".join(
            f'<li><a href="/{sugg}">{sugg}</a></li>'
            for sugg in suggestions[:5]
        )

        return f"""\
<div class="suggestion">
    <strong>Did you mean:</strong>
    <ul>
        {items_html}
    </ul>
</div>
"""

    @staticmethod
    def _similar(a, b):
        """Simple string similarity ratio using edit distance."""
        if len(a) > len(b):
            a, b = b, a
        distances = range(len(a) + 1)
        for i2, c2 in enumerate(b):
            distances_ = [i2 + 1]
            for i1, c1 in enumerate(a):
                if c1 == c2:
                    distances_.append(distances[i1])
                else:
                    distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
            distances = distances_
        return 1 - (distances[-1] / max(len(a), len(b)))
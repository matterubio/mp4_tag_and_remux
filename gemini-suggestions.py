import requests
import subprocess
import os

# --- Configuration ---
# Get your API key from www.themoviedb.org
TMDB_API_KEY = "YOUR_TMDB_API_KEY" 
MOVIE_TITLE = "Inception"  # Replace with the movie you want to search for
INPUT_FILE = "input_movie.mp4"  # Replace with your input video file path
OUTPUT_FILE = "output_movie_with_metadata.mp4" # Desired output file path

def search_movie(title, api_key):
    """Searches TMDb for a movie and returns the first result's ID and poster URL."""
    search_url = f"api.themoviedb.org{api_key}&query={title}"
    response = requests.get(search_url)
    data = response.json()
    if data['results']:
        first_result = data['results'][0]
        movie_id = first_result['id']
        # Poster URL path; need to prepend base URL later
        poster_path = first_result.get('poster_path') 
        return movie_id, poster_path
    return None, None

def get_movie_details(movie_id, api_key):
    """Fetches details for a specific movie ID."""
    details_url = f"api.themoviedb.org{movie_id}?api_key={api_key}"
    response = requests.get(details_url)
    return response.json()

def download_poster(poster_path, api_key, filename="poster.jpg"):
    """Downloads the movie poster image."""
    # Common TMDb image base URL (adjust size as needed, e.g., 'w500')
    image_base_url = "image.tmdb.org" 
    if poster_path:
        image_url = f"{image_base_url}{poster_path}"
        response = requests.get(image_url)
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(response.content)
            return filename
    return None

def apply_metadata_and_remux(input_file, output_file, metadata, poster_file=None):
    """Uses FFmpeg to apply metadata and poster image to the video file."""
    command = ['ffmpeg', '-i', input_file]
    
    if poster_file and os.path.exists(poster_file):
        command.extend(['-i', poster_file, '-map', '0:v:0', '-map', '0:a?', '-map', '1:v:0', '-c:v:0', 'copy', '-c:a', 'copy', '-c:v:1', 'mjpeg', '-disposition:v:1', 'attached_pic'])
    else:
        command.extend(['-c', 'copy']) # copy codecs if no poster is added

    # Add metadata flags
    for key, value in metadata.items():
        command.extend(['-metadata', f"{key}={value}"])
    
    # Ensure metadata tags are written to file format (especially for MP4/MOV)
    command.extend(['-movflags', 'use_metadata_tags', output_file]) 

    print(f"Running FFmpeg command: {' '.join(command)}")
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"Successfully remuxed file saved as {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error: {e.stderr.decode()}")
    except FileNotFoundError:
        print("Error: ffmpeg command not found. Please ensure FFmpeg is installed and in your system's PATH.")


# --- Main execution ---
if __name__ == "__main__":
    if TMDB_API_KEY == "YOUR_TMDB_API_KEY":
        print("Please set your TMDB_API_KEY in the script.")
    elif not os.path.exists(INPUT_FILE):
         print(f"Error: Input file '{INPUT_FILE}' not found.")
    else:
        movie_id, poster_path = search_movie(MOVIE_TITLE, TMDB_API_KEY)
        if movie_id:
            details = get_movie_details(movie_id, TMDB_API_KEY)
            
            # Extract relevant metadata
            title = details.get('title')
            year = details.get('release_date', '')[:4] # Get only the year
            overview = details.get('overview')

            metadata_dict = {
                'title': title,
                'year': year,
                'comment': overview, # Using 'comment' tag for overview/synopsis
                # You can add more standard tags like 'artist', 'genre', etc.
            }
            
            # Download poster
            poster_file_name = None
            if poster_path:
                print("Downloading poster...")
                poster_file_name = download_poster(poster_path, TMDB_API_KEY)

            # Apply metadata
            print(f"Applying metadata to {INPUT_FILE}...")
            apply_metadata_and_remux(INPUT_FILE, OUTPUT_FILE, metadata_dict, poster_file_name)
            
            # Clean up poster file
            if poster_file_name and os.path.exists(poster_file_name):
                os.remove(poster_file_name)
                print(f"Removed temporary poster file {poster_file_name}")

        else:
            print(f"Could not find movie '{MOVIE_TITLE}' 
on TMDb.")

